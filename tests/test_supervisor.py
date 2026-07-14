"""M-A supervisor identity tests (spec §4): state files, journal format,
claim/seizure/handshake state machine, boot ritual, handoff, nag."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with an active GOALS.md and seeded journal."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- entry one\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    return tmp_path


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


class TestStateFiles:
    def test_incarnation_roundtrip_atomic(self, sup_home):
        claim = {"incarnation_id": "inc-20260714T110000Z-abcd", "session_id": "sid-1",
                 "claimed_at": _iso(NOW), "heartbeat_at": _iso(NOW), "claimed_via": "fresh"}
        fleet.write_incarnation(claim)
        assert fleet.read_incarnation() == claim
        # atomic: no .tmp litter left behind
        assert not list((sup_home / "supervisor").glob("*.tmp"))

    def test_read_incarnation_missing_and_corrupt(self, sup_home):
        assert fleet.read_incarnation() is None
        fleet.incarnation_path().write_text("{not json", encoding="utf-8")
        assert fleet.read_incarnation() is None

    def test_handshake_roundtrip(self, sup_home):
        fleet.write_handshake("inc-x", "sid-9")
        hs = fleet.read_handshake()
        assert hs["incarnation_id"] == "inc-x" and hs["session_id"] == "sid-9"
        assert "written_at" in hs

    def test_mint_incarnation_id_format_and_uniqueness(self, sup_home):
        a, b = fleet.mint_incarnation_id(), fleet.mint_incarnation_id()
        assert a.startswith("inc-") and a != b
        import re
        assert re.fullmatch(r"inc-\d{8}T\d{6}Z-[0-9a-f]{4}", a)


class TestJournal:
    def test_append_creates_seed_and_parses_back(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "fresh claim")
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1", "line one\nline two")
        text = fleet.supervisor_journal_path().read_text(encoding="utf-8")
        assert text.startswith("# Supervisor Journal")
        entries = fleet.supervisor_journal_entries()
        assert [e["kind"] for e in entries] == ["BOOT", "CHECKPOINT"]
        assert entries[1]["body"].strip() == "line one\nline two"
        assert entries[1]["inc"] == "inc-a" and entries[1]["sid"] == "sid-1"
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "CHECKPOINT"

    def test_append_rejects_unknown_kind(self, sup_home):
        with pytest.raises(ValueError):
            fleet.supervisor_journal_append("SABOTAGE", "inc-a", "sid-1", "x")

    def test_parser_tolerates_prose_between_entries(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "ok")
        with open(fleet.supervisor_journal_path(), "a", encoding="utf-8") as f:
            f.write("\nstray human note, not an entry header\n")
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1", "next")
        assert [e["kind"] for e in fleet.supervisor_journal_entries()] == ["BOOT", "CHECKPOINT"]

    def test_empty_journal(self, sup_home):
        assert fleet.supervisor_journal_entries() == []
        assert fleet.supervisor_journal_latest() is None


def _claim(inc="inc-old", sid="sid-old", beat=None):
    beat = beat or NOW - timedelta(seconds=60)
    return {"incarnation_id": inc, "session_id": sid,
            "claimed_at": _iso(NOW - timedelta(hours=2)),
            "heartbeat_at": _iso(beat), "claimed_via": "fresh"}


class TestClaimDecision:
    def test_no_claim_file_claims(self):
        v, _ = fleet.supervisor_claim_decision(None, set(), None, now=NOW)
        assert v == "claim"

    def test_live_in_roster_refuses(self):
        v, _ = fleet.supervisor_claim_decision(_claim(), {"sid-old"}, None, now=NOW)
        assert v == "refuse"

    def test_roster_gone_stale_heartbeat_seizes(self):
        c = _claim(beat=NOW - timedelta(seconds=3601))
        v, _ = fleet.supervisor_claim_decision(c, set(), None, now=NOW)
        assert v == "seize"

    def test_roster_gone_fresh_heartbeat_freezes(self):
        c = _claim(beat=NOW - timedelta(seconds=120))
        v, reason = fleet.supervisor_claim_decision(c, set(), None, now=NOW)
        assert v == "freeze"
        assert "G9" in reason or "daemon" in reason.lower()

    def test_fresher_foreign_checkpoint_refuses(self):
        # journal's latest entry is a DIFFERENT incarnation, newer than the
        # claim's heartbeat -> mid-transition, bystander must refuse (spec §4)
        c = _claim(beat=NOW - timedelta(seconds=7200))
        latest = {"ts": _iso(NOW - timedelta(seconds=30)), "kind": "CHECKPOINT",
                  "inc": "inc-newer", "sid": "sid-newer", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "refuse"

    def test_own_incarnation_checkpoint_does_not_block_seize(self):
        c = _claim(inc="inc-old", beat=NOW - timedelta(seconds=7200))
        latest = {"ts": _iso(NOW - timedelta(seconds=7100)), "kind": "CHECKPOINT",
                  "inc": "inc-old", "sid": "sid-old", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "seize"

    def test_unparseable_heartbeat_freezes_never_seizes(self):
        c = _claim()
        c["heartbeat_at"] = "garbage"
        v, _ = fleet.supervisor_claim_decision(c, set(), None, now=NOW)
        assert v == "freeze"


class TestEpochCheck:
    def test_roster_fetch_failure_freezes(self):
        ok, reason = fleet.supervisor_epoch_check(False, "claude not on PATH")
        assert ok is False and "claude not on PATH" in reason

    def test_empty_roster_is_suspicious(self):
        # the booting session itself is a claude session -- an --all roster
        # with ZERO entries means the daemon lost its memory (G9 shape)
        ok, reason = fleet.supervisor_epoch_check(True, [])
        assert ok is False

    def test_populated_roster_passes(self):
        ok, _ = fleet.supervisor_epoch_check(True, [{"sessionId": "s1", "status": "idle"}])
        assert ok is True


class TestRosterLiveSids:
    def test_status_or_pid_means_live(self):
        entries = [
            {"sessionId": "a", "status": "busy", "pid": 1, "state": "working"},
            {"sessionId": "b", "state": "done"},              # dead: no status/pid
            {"sessionId": "c", "status": "idle"},             # interactive: live
            {"sessionId": "d", "state": "working"},           # wedged, no pid/status: NOT live
            {"no_sid": True, "status": "idle"},               # malformed: skipped
        ]
        assert fleet._roster_live_sids(entries) == {"a", "c"}


def _fake_run_roster(entries):
    """Injectable subprocess.run double returning a roster JSON payload."""
    def run(argv, **kw):
        assert "--json" in argv and "--all" in argv
        return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
    return run


def _fake_which(name):
    return "C:/fake/claude.cmd"


class TestSupBoot:
    def _boot(self, sup_home, entries, sid="sid-me", handoff=None):
        args = SimpleNamespace(sid=sid, handoff_inc=handoff)
        return fleet.cmd_sup_boot(args, which=_fake_which, run=_fake_run_roster(entries))

    def test_fresh_claim_writes_incarnation_and_boot_checkpoint(self, sup_home, capsys):
        rc = self._boot(sup_home, [{"sessionId": "sid-me", "status": "busy"}])
        assert rc == 0
        claim = fleet.read_incarnation()
        assert claim["session_id"] == "sid-me" and claim["claimed_via"] == "fresh"
        entries = fleet.supervisor_journal_entries()
        assert entries[-1]["kind"] == "BOOT"
        out = capsys.readouterr().out
        assert "VERDICT: claim" in out and "GOALS" in out and "entry one" in out

    def test_refuse_is_strictly_read_only(self, sup_home, capsys):
        live_holder = _claim(sid="sid-holder")
        fleet.write_incarnation(live_holder)
        before_journal = fleet.supervisor_journal_entries()
        fleet.write_handshake("inc-inflight", "sid-x")  # in-flight handoff artifact
        rc = self._boot(sup_home, [{"sessionId": "sid-holder", "status": "idle"},
                                   {"sessionId": "sid-me", "status": "busy"}])
        assert rc == 2
        assert fleet.read_incarnation() == live_holder          # untouched
        assert fleet.read_handshake() is not None               # bystander never deletes (spec §4)
        assert fleet.supervisor_journal_entries() == before_journal
        assert "VERDICT: refuse" in capsys.readouterr().out

    def test_seize_rewrites_claim_deletes_handshake_journals_seized(self, sup_home, capsys):
        stale = _claim(inc="inc-dead", sid="sid-dead",
                       beat=datetime.now(timezone.utc) - timedelta(hours=3))
        fleet.write_incarnation(stale)
        fleet.write_handshake("inc-orphan", "sid-orphan")  # crash-mid-handoff orphan
        rc = self._boot(sup_home, [{"sessionId": "sid-me", "status": "busy"}])
        assert rc == 0
        claim = fleet.read_incarnation()
        assert claim["session_id"] == "sid-me" and claim["claimed_via"] == "seize"
        assert fleet.read_handshake() is None                   # stale-HANDSHAKE hygiene
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "SEIZED" and "inc-dead" in latest["body"]

    def test_freeze_on_fresh_heartbeat_roster_gone(self, sup_home, capsys):
        fresh = _claim(sid="sid-gone", beat=datetime.now(timezone.utc) - timedelta(seconds=30))
        fleet.write_incarnation(fresh)
        rc = self._boot(sup_home, [{"sessionId": "sid-me", "status": "busy"}])
        assert rc == 3
        assert fleet.read_incarnation() == fresh
        assert "VERDICT: freeze" in capsys.readouterr().out

    def test_freeze_on_empty_roster_even_with_no_claim(self, sup_home, capsys):
        rc = self._boot(sup_home, [])
        assert rc == 3
        assert fleet.read_incarnation() is None  # epoch freeze blocks even a fresh claim

    def test_handoff_mode_writes_handshake_touches_nothing_else(self, sup_home, capsys):
        holder = _claim(sid="sid-old")
        fleet.write_incarnation(holder)
        before_journal = fleet.supervisor_journal_entries()
        rc = self._boot(sup_home, [{"sessionId": "sid-old", "status": "idle"},
                                   {"sessionId": "sid-me", "status": "busy"}],
                        handoff="inc-successor")
        assert rc == 0
        hs = fleet.read_handshake()
        assert hs["incarnation_id"] == "inc-successor" and hs["session_id"] == "sid-me"
        assert fleet.read_incarnation() == holder
        assert fleet.supervisor_journal_entries() == before_journal
        assert "handshake-written" in capsys.readouterr().out

    def test_no_sid_available_is_cli_error(self, sup_home):
        args = SimpleNamespace(sid=None, handoff_inc=None)
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_boot(args, which=_fake_which, run=_fake_run_roster([]))


class TestCheckpointHeartbeat:
    def _hold(self, sid="sid-me", inc="inc-me"):
        # Seed the heartbeat strictly in the past: now_iso() truncates to
        # whole seconds, so a same-second seed would let `>=` pass on
        # equality even if the refresh silently stopped happening.
        beat = (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh"})

    def test_checkpoint_appends_and_refreshes_heartbeat(self, sup_home):
        self._hold()
        old_beat = fleet.read_incarnation()["heartbeat_at"]
        args = SimpleNamespace(body="did a thing", kind="CHECKPOINT", sid="sid-me")
        assert fleet.cmd_sup_checkpoint(args) == 0
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "CHECKPOINT" and latest["body"] == "did a thing"
        assert latest["inc"] == "inc-me"
        assert fleet.read_incarnation()["heartbeat_at"] > old_beat

    def test_non_holder_refused_journal_untouched(self, sup_home):
        self._hold(sid="sid-holder")
        args = SimpleNamespace(body="intruder", kind="CHECKPOINT", sid="sid-intruder")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(args)
        assert fleet.supervisor_journal_entries() == []

    def test_checkpoint_without_any_claim_refused(self, sup_home):
        args = SimpleNamespace(body="x", kind="CHECKPOINT", sid="sid-me")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(args)

    def test_heartbeat_refreshes_without_journal_growth(self, sup_home):
        self._hold()
        args = SimpleNamespace(sid="sid-me")
        assert fleet.cmd_sup_heartbeat(args) == 0
        assert fleet.supervisor_journal_entries() == []
        assert fleet.read_incarnation()["heartbeat_at"] is not None


class TestSupStatus:
    def test_json_shape(self, sup_home, capsys):
        fleet.write_incarnation({"incarnation_id": "inc-me", "session_id": "sid-me",
                                 "claimed_at": _iso(NOW), "heartbeat_at": fleet.now_iso(),
                                 "claimed_via": "fresh"})
        args = SimpleNamespace(json=True)
        assert fleet.cmd_sup_status(args) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["goals_active"] is True
        assert data["incarnation"]["incarnation_id"] == "inc-me"
        assert data["heartbeat_age_seconds"] < 60
        assert data["handshake"] is None and data["abort_flag"] is False

    def test_no_claim_human_output(self, sup_home, capsys):
        args = SimpleNamespace(json=False)
        assert fleet.cmd_sup_status(args) == 0
        assert "no claim" in capsys.readouterr().out.lower()


class TestHandoff:
    def _hold(self, sid="sid-old", inc="inc-old"):
        fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                                 "claimed_at": _iso(NOW), "heartbeat_at": _iso(NOW),
                                 "claimed_via": "fresh"})

    def _begin(self, run, sid="sid-old"):
        args = SimpleNamespace(sid=sid, model=None, permission_mode=None)
        return fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=lambda s: None)

    @staticmethod
    def _dispatch_then_roster(successor_sid="sid-new"):
        """run double. Call order in cmd_sup_handoff_begin is: pre-dispatch
        roster fetch, --bg dispatch, then roster polls -- so the fake is
        STATEFUL: the successor appears in the roster only after the
        dispatch call has been observed."""
        state = {"name": None}
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            if "--bg" in argv:
                state["name"] = next(a for a in argv if a.startswith("sup|"))
                return SimpleNamespace(returncode=0, stdout="backgrounded · abc123 · sup\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["name"]:
                entries.append({"sessionId": successor_sid, "status": "busy",
                                "name": state["name"]})
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        run.calls = calls
        return run

    def test_begin_journals_writes_taskfile_joins_sid(self, sup_home, capsys):
        self._hold()
        run = self._dispatch_then_roster()
        rc = self._begin(run)
        assert rc == 0
        latest_kinds = [e["kind"] for e in fleet.supervisor_journal_entries()]
        assert "HANDOFF-BEGIN" in latest_kinds
        out = capsys.readouterr().out
        assert "SUCCESSOR-SID: sid-new" in out and "SUCCESSOR-INC: inc-" in out
        taskfiles = list((sup_home / "state").glob("supervisor-handoff-*.md"))
        assert len(taskfiles) == 1
        body = taskfiles[0].read_text(encoding="utf-8")
        assert "sup-boot --handoff-inc" in body and "NO spawn" in body
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert any(a.startswith("sup|inc-") for a in dispatch)

    def test_begin_doa_when_successor_never_appears(self, sup_home, capsys, monkeypatch):
        # shrink the verify window: with a no-op sleep the real 60s window
        # would busy-spin for a full minute of wall clock
        monkeypatch.setattr(fleet, "SUPERVISOR_ROSTER_VERIFY_SECONDS", 0.05)
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=0, stdout="backgrounded · abc · sup\n", stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                [{"sessionId": "sid-old", "status": "busy"}]), stderr="")
        rc = self._begin(run)
        assert rc == 1
        assert "DOA" in capsys.readouterr().out

    def test_begin_refused_for_non_holder(self, sup_home):
        self._hold(sid="sid-holder")
        with pytest.raises(fleet.FleetCliError):
            self._begin(self._dispatch_then_roster(), sid="sid-imposter")

    def test_complete_transfers_on_dual_match(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-new")
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ", expect_sid="sid-new")
        assert fleet.cmd_sup_handoff_complete(args) == 0
        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == "inc-succ" and claim["session_id"] == "sid-new"
        assert claim["claimed_via"] == "handoff"
        assert fleet.read_handshake() is None
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "HANDOFF-COMPLETE" and latest["inc"] == "inc-old"

    def test_complete_refuses_on_inc_mismatch(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-WRONG", "sid-new")
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_handoff_complete(args)
        assert fleet.read_incarnation()["incarnation_id"] == "inc-old"
        assert fleet.read_handshake() is not None

    def test_complete_refuses_when_no_handshake(self, sup_home):
        self._hold()
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_handoff_complete(args)

    def test_abort_stops_successor_flags_and_resumes(self, sup_home, capsys):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-new")
        stopped = []
        def run(argv, **kw):
            stopped.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-new")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert stopped and stopped[0][-2:] == ["stop", "sid-new"]
        assert fleet.read_handshake() is None
        assert fleet.handoff_abort_flag_path().exists()
        assert fleet.supervisor_journal_latest()["kind"] == "HANDOFF-ABORT"
        assert fleet.read_incarnation()["incarnation_id"] == "inc-old"  # old resumes duty

    def test_abort_reports_failed_stop_but_still_flags(self, sup_home, capsys):
        self._hold()
        def run(argv, **kw):
            return SimpleNamespace(returncode=1, stdout="", stderr="no such session")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-gone")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert fleet.handoff_abort_flag_path().exists()
        assert "stop failed" in capsys.readouterr().out.lower()

    def test_begin_clears_previous_abort_flag(self, sup_home):
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {"stale": True})
        self._begin(self._dispatch_then_roster())
        assert not fleet.handoff_abort_flag_path().exists()

    def test_handoff_timeout_drill_end_to_end(self, sup_home):
        """Spec §4 failure branch: begin -> successor never handshakes ->
        complete refuses -> abort stops the limbo successor and old resumes."""
        self._hold()
        rc = self._begin(self._dispatch_then_roster())
        assert rc == 0
        args = SimpleNamespace(sid="sid-old",
                               expect_inc="inc-whatever", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):   # no HANDSHAKE was written
            fleet.cmd_sup_handoff_complete(args)
        def stop_run(argv, **kw):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        abort = SimpleNamespace(sid="sid-old", successor_sid="sid-new")
        assert fleet.cmd_sup_handoff_abort(abort, which=_fake_which, run=stop_run) == 0
        assert fleet.read_incarnation()["session_id"] == "sid-old"


class TestNag:
    def test_none_when_goals_absent(self, sup_home):
        fleet.goals_path().unlink()
        assert fleet.supervisor_status_line() is None

    def test_none_when_dormant_token(self, sup_home):
        fleet.goals_path().write_text("# Goals\nSUPERVISOR-DORMANT\n", encoding="utf-8")
        assert fleet.supervisor_status_line() is None

    def test_nags_when_no_claim(self, sup_home):
        line = fleet.supervisor_status_line()
        assert line is not None and "no claim" in line

    def test_nags_when_heartbeat_stale(self, sup_home):
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        fleet.write_incarnation({"incarnation_id": "inc-x", "session_id": "s",
                                 "claimed_at": _iso(stale), "heartbeat_at": _iso(stale),
                                 "claimed_via": "fresh"})
        line = fleet.supervisor_status_line()
        assert "stale" in line

    def test_informational_when_fresh(self, sup_home):
        fleet.write_incarnation({"incarnation_id": "inc-x", "session_id": "s",
                                 "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
                                 "claimed_via": "fresh"})
        line = fleet.supervisor_status_line()
        assert "inc-x" in line and "stale" not in line and "no claim" not in line


class TestSupervisorDoctorChecks:
    def test_claim_check_is_always_advisory_pass(self, sup_home):
        name, ok, msg = fleet._doctor_check_supervisor_claim()
        assert name == "supervisor-claim" and ok is True
        assert "no claim" in msg

    def test_handoff_check_fails_on_abort_flag(self, sup_home):
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {"aborted_at": "x"})
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is False and "abort" in msg.lower()

    def test_handoff_check_fails_on_stale_handshake(self, sup_home):
        fleet.write_handshake("inc-x", "sid-x")
        import os as _os, time as _time
        old = _time.time() - fleet.SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS - 60
        _os.utime(fleet.handshake_path(), (old, old))
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is False and "stale" in msg.lower()

    def test_handoff_check_passes_on_fresh_handshake(self, sup_home):
        fleet.write_handshake("inc-x", "sid-x")
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is True and "in flight" in msg

    def test_handoff_check_passes_clean(self, sup_home):
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is True


class TestSessionStartLine:
    def test_build_context_includes_supervisor_nag(self, sup_home, monkeypatch):
        import importlib.util
        # _build_context() short-circuits to "" when status_snapshot() reports
        # a missing registry ("not_initialized") -- seed an empty-but-valid one
        # HERE, not in sup_home: the shared fixture must keep the registry
        # absent so TestSupBoot still covers the registry-unreadable branch.
        (sup_home / "state" / "fleet.json").write_text(
            json.dumps({"workers": {}}), encoding="utf-8")
        hook_path = (fleet.Path(fleet.__file__).resolve().parent / "hooks"
                     / "sessionstart_fleet.py")
        spec = importlib.util.spec_from_file_location("sessionstart_fleet", hook_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "fleet", fleet)   # hook resolves its own fleet import
        ctx = mod._build_context()
        assert "SUPERVISOR:" in ctx
