"""M-A supervisor identity tests (spec §4): state files, journal format,
claim/seizure/handshake state machine, boot ritual, handoff, nag."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
    # Rendered worker-settings instance: the successor dispatch carries it as
    # --settings and refuses when it is absent (SPEC §6, second dispatch path).
    (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}', encoding="utf-8")
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

    def test_header_injection_in_body_is_escaped(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "ok")
        evil_line = "## 2099-01-01T00:00:00Z CHECKPOINT inc=inc-evil sid=sid-evil"
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1",
                                        f"legit body\n{evil_line}\nmore legit body")
        entries = fleet.supervisor_journal_entries()
        assert [e["kind"] for e in entries] == ["BOOT", "CHECKPOINT"]
        assert entries[1]["inc"] == "inc-a" and entries[1]["sid"] == "sid-1"
        assert evil_line in entries[1]["body"]
        latest = fleet.supervisor_journal_latest()
        assert latest["inc"] != "inc-evil"
        assert latest["inc"] == "inc-a"


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

    def test_foreign_but_not_fresher_checkpoint_falls_through_to_seize(self):
        # journal's latest entry is a DIFFERENT incarnation but OLDER than
        # the claim's heartbeat -- the normal dead-post-handoff-successor
        # recovery path. A "refuse on any foreign inc" refactor must fail
        # this test.
        c = _claim(inc="inc-old", beat=NOW - timedelta(seconds=7200))
        latest = {"ts": _iso(NOW - timedelta(seconds=8000)), "kind": "CHECKPOINT",
                  "inc": "inc-other", "sid": "sid-other", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "seize"

    def test_foreign_checkpoint_unparseable_ts_falls_through(self):
        c = _claim(inc="inc-old", beat=NOW - timedelta(seconds=7200))
        latest = {"ts": "garbage", "kind": "CHECKPOINT",
                  "inc": "inc-other", "sid": "sid-other", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "seize"


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

    def test_hostile_sessionid_value_filtered_not_raised(self):
        # Debt roll-up item 2, third grepped site: a dict-valued sessionId
        # (CLI drift / hostile roster) must be filtered, never raise
        # TypeError from an unhashable value landing in the live-sid set.
        entries = [
            {"sessionId": {"nested": "hostile"}, "status": "busy"},
            {"sessionId": ["also", "unhashable"], "pid": 7},
            {"sessionId": "ok", "status": "idle"},
        ]
        assert fleet._roster_live_sids(entries) == {"ok"}


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
    def _dispatch_then_roster(successor_sid="succ0001-full", short_id="succ0001"):
        """run double. Call order in cmd_sup_handoff_begin is: pre-dispatch
        roster fetch, --bg dispatch, then roster polls by short-id prefix
        (contract G6) -- so the fake is STATEFUL: the successor appears in
        the roster only after the dispatch call has been observed.
        `successor_sid` must start with `short_id` for the join to succeed."""
        assert successor_sid.startswith(short_id)
        state = {"dispatched": False}
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            if "--bg" in argv:
                state["dispatched"] = True
                return SimpleNamespace(returncode=0,
                                       stdout=f"backgrounded · {short_id} · sup\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["dispatched"]:
                entries.append({"sessionId": successor_sid, "status": "busy"})
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
        assert "SUCCESSOR-SID: succ0001-full" in out and "SUCCESSOR-INC: inc-" in out
        taskfiles = list((sup_home / "state").glob("supervisor-handoff-*.md"))
        assert len(taskfiles) == 1
        body = taskfiles[0].read_text(encoding="utf-8")
        assert "sup-boot --handoff-inc" in body and "NO spawn" in body
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert any(a.startswith("sup|inc-") for a in dispatch)

    def test_begin_pre_snapshot_filters_hostile_sessionid_value(self, sup_home):
        # Roll-up item 3: a dict-valued sessionId in the roster payload (CLI
        # drift / hostile roster) must not raise TypeError from an
        # unhashable value landing in cmd_sup_handoff_begin's own pre_sids
        # exclusion set.
        self._hold()
        state = {"dispatched": False}
        def run(argv, **kw):
            if "--bg" in argv:
                state["dispatched"] = True
                return SimpleNamespace(returncode=0,
                                       stdout="backgrounded · succ0001 · sup\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"},
                       {"sessionId": {"nested": "hostile"}, "status": "busy"}]
            if state["dispatched"]:
                entries.append({"sessionId": "succ0001-full", "status": "busy"})
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        rc = self._begin(run)
        assert rc == 0

    def test_successor_dispatch_passes_fleet_home_cwd(self, sup_home):
        self._hold()
        kwargs_seen = []
        run = self._dispatch_then_roster()
        def wrapped(argv, **kw):
            kwargs_seen.append(kw)
            return run(argv, **kw)
        rc = self._begin(wrapped)
        assert rc == 0
        dispatch_kwargs = next(kw for kw, argv in zip(kwargs_seen, run.calls) if "--bg" in argv)
        assert dispatch_kwargs["cwd"] == str(sup_home)

    # --- Defect A: the sanctioned second dispatch path (SPEC §6) -----------
    #
    # `cmd_sup_handoff_begin` does NOT go through `dispatch_bg` -- it cannot:
    # an incarnation id (`inc-<8>T<6>Z-<4>`) carries uppercase T/Z and so fails
    # `NAME_RE` at the choke point's own guard, and the successor's task file is
    # already written to `state/supervisor-handoff-<inc>.md` and journaled by
    # path, which `task_file_path(name)` would duplicate. The tests below pin
    # the contract that makes the second path SANCTIONED rather than a bypass:
    # it must carry the same hook wiring and the same process-identity hygiene
    # the choke point carries.

    def test_successor_dispatch_carries_instance_settings(self, sup_home):
        """Defect A: a successor launched WITHOUT --settings gets none of
        fleet's hooks (Stop outcome, Stop mailbox, PostToolUse mailbox,
        PostCompact journal). All four degrade to sid-keyed writes when the
        session has no registry record, so a successor genuinely benefits --
        and its sid is exactly the handle sup-handoff-complete/-abort use."""
        self._hold()
        run = self._dispatch_then_roster()
        assert self._begin(run) == 0
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert "--settings" in dispatch
        assert (dispatch[dispatch.index("--settings") + 1]
                == fleet.instance_settings_path().as_posix())

    def test_successor_dispatch_refused_without_rendered_settings(self, sup_home):
        """Same doctrine as cmd_spawn's `_require_instance_settings`: claude
        silently ignores a --settings path that does not exist, so a missing
        instance would put the hookless successor back with no error anywhere.
        Fail closed BEFORE the journal entry and the task file are written."""
        self._hold()
        fleet.instance_settings_path().unlink()
        run = self._dispatch_then_roster()
        with pytest.raises(fleet.FleetCliError, match="worker settings instance missing"):
            self._begin(run)
        assert not any("--bg" in c for c in run.calls)
        assert [e["kind"] for e in fleet.supervisor_journal_entries()] == []
        assert list((sup_home / "state").glob("supervisor-handoff-*.md")) == []

    def test_successor_dispatch_always_carries_a_permission_mode(self, sup_home):
        """B4/D6: `dispatch_bg` ends every worker argv with `mode_flags(mode)`
        and every worker defaults to `dontask`. The successor emitted a
        permission flag ONLY when the operator typed `--permission-mode`
        (argparse default None), so the default path ran under claude's own
        default mode -- and the successor's bootstrap opens with a Bash call,
        which in a headless `--bg` session hangs forever on an unanswerable
        permission prompt. That is the T12 wedge class this repo already paid
        for once."""
        self._hold()
        run = self._dispatch_then_roster()
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None)
        assert fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=lambda s: None) == 0
        dispatch = next(c for c in run.calls if "--bg" in c)
        expected = fleet.mode_flags(fleet.SUCCESSOR_DEFAULT_MODE)
        assert expected, "the successor default mode must emit at least one flag"
        for flag in expected:
            assert flag in dispatch
        # same default the worker choke point uses -- not a bespoke one
        assert fleet.SUCCESSOR_DEFAULT_MODE in fleet.MODE_FLAGS

    def test_explicit_permission_mode_overrides_the_successor_default(self, sup_home):
        self._hold()
        run = self._dispatch_then_roster()
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode="plan")
        assert fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=lambda s: None) == 0
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert dispatch[dispatch.index("--permission-mode") + 1] == "plan"
        # exactly one mode opinion on the argv, never the default alongside it
        assert dispatch.count("--permission-mode") == 1
        assert "--dangerously-skip-permissions" not in dispatch

    def test_successor_mode_uses_one_vocabulary_everywhere(self, sup_home):
        """G3: the explicit branch took a RAW CLAUDE mode string while the
        default branch took a FLEET mode name through `mode_flags()` -- two
        vocabularies for one argument. Both branches now speak fleet mode
        names, so `--permission-mode bypass` reaches the argv as
        `--dangerously-skip-permissions`, exactly as `fleet spawn --mode
        bypass` does. A raw claude spelling is refused by argparse rather than
        silently forwarded."""
        self._hold()
        run = self._dispatch_then_roster()
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode="bypass")
        assert fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=lambda s: None) == 0
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert dispatch[-2:] != ["--permission-mode", "bypass"]
        assert "--dangerously-skip-permissions" in dispatch
        assert "--permission-mode" not in dispatch

    def test_successor_permission_mode_is_constrained_to_fleet_mode_names(self):
        """G3, the enforcement half: the parser must reject a vocabulary the
        dispatch cannot speak. Without `choices`, `--permission-mode acceptEdits`
        parsed fine and then raised ValueError deep inside `mode_flags`."""
        parser = fleet.build_parser()
        args = parser.parse_args(["sup-handoff-begin", "--permission-mode", "accept"])
        assert args.permission_mode == "accept"
        with pytest.raises(SystemExit):
            parser.parse_args(["sup-handoff-begin", "--permission-mode", "acceptEdits"])

    def test_missing_claude_refuses_before_journal_and_taskfile(self, sup_home):
        """B5: `resolve_claude_executable` is the same class of pre-flight as
        `_require_instance_settings` -- a missing external prerequisite. It ran
        AFTER the journal write, the task-file write and the prior abort flag's
        deletion, and raises `ClaudeNotFoundError` with no `_abort_flag` guard,
        so a `claude` that dropped off PATH left HANDOFF-BEGIN journaled with no
        successor and nothing for doctor to see -- contradicting the docstring's
        promise that both failure paths raise the flag."""
        self._hold()
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        with pytest.raises(fleet.FleetCliError, match="claude executable not found"):
            fleet.cmd_sup_handoff_begin(SimpleNamespace(sid="sid-old", model=None,
                                                        permission_mode=None),
                                        which=lambda _n: None, run=run,
                                        sleep=lambda s: None)
        assert fleet.supervisor_journal_entries() == []
        assert list((sup_home / "state").glob("supervisor-handoff-*.md")) == []
        assert calls == []

    def test_missing_claude_leaves_a_prior_abort_flag_intact(self, sup_home):
        """The refusal must not consume the previous handoff's evidence: the
        `unlink()` of the abort flag sits inside the lock, after the pre-flights."""
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(),
                                 {"reason": "successor-doa", "holder": "inc-older"})
        with pytest.raises(fleet.FleetCliError, match="claude executable not found"):
            fleet.cmd_sup_handoff_begin(SimpleNamespace(sid="sid-old", model=None,
                                                        permission_mode=None),
                                        which=lambda _n: None,
                                        run=lambda *a, **k: SimpleNamespace(
                                            returncode=0, stdout="[]", stderr=""),
                                        sleep=lambda s: None)
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "successor-doa"

    def test_successor_dispatch_uses_worker_env(self, sup_home, monkeypatch):
        """§5.1 provenance: without `env=_worker_env(name)` the successor
        inherits the OLD supervisor's CLAUDE_CODE_SESSION_ID. `cmd_sup_boot`
        reads exactly that variable (@caller_sid) and writes it into the
        HANDSHAKE, so an inherited value makes the successor hand back the old
        holder's sid -- and `sup-handoff-complete --expect-sid <successor_sid>`
        then refuses on a mismatch, wedging the handoff. Same reason
        `dispatch_bg` strips it at every worker launch."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-old")
        self._hold()
        kwargs_seen = []
        run = self._dispatch_then_roster()
        def wrapped(argv, **kw):
            kwargs_seen.append(kw)
            return run(argv, **kw)
        assert self._begin(wrapped) == 0
        env = next(kw for kw, argv in zip(kwargs_seen, run.calls) if "--bg" in argv)["env"]
        assert "CLAUDE_CODE_SESSION_ID" not in env
        assert env["FLEET_WORKER"].startswith("sup|inc-")
        assert env["PATH"] == os.environ["PATH"]  # inherited env, not a bare one

    def test_successor_join_uses_short_id_prefix(self, sup_home, capsys):
        """ai-title collision hazard: TWO fresh roster entries share the
        successor's display name; only the sid whose prefix matches the
        dispatch-printed short id may be joined."""
        self._hold()
        state = {"dispatched": False}
        def run(argv, **kw):
            if "--bg" in argv:
                state["dispatched"] = True
                return SimpleNamespace(returncode=0, stdout="backgrounded · abc999 · sup\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["dispatched"]:
                entries += [
                    {"sessionId": "abc999-genuine", "status": "busy", "name": "sup|collided|successor"},
                    {"sessionId": "def000-imposter", "status": "busy", "name": "sup|collided|successor"},
                ]
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        rc = self._begin(run)
        assert rc == 0
        assert "SUCCESSOR-SID: abc999-genuine" in capsys.readouterr().out

    def test_join_falls_back_to_name_join_when_short_id_unparseable(self, sup_home, capsys):
        self._hold()
        state = {"name": None}
        def run(argv, **kw):
            if "--bg" in argv:
                state["name"] = next(a for a in argv if a.startswith("sup|"))
                return SimpleNamespace(returncode=0, stdout="launched (no short id token)\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["name"]:
                entries.append({"sessionId": "sid-fallback-joined", "status": "busy",
                                "name": state["name"]})
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        rc = self._begin(run)
        assert rc == 0
        out = capsys.readouterr().out
        assert "falling back to name join (G6 fallback)" in out
        assert "SUCCESSOR-SID: sid-fallback-joined" in out

    def test_name_join_fallback_filters_hostile_sessionid_value(self, sup_home, capsys):
        # Debt roll-up item 2, fourth grepped site: the G6 name-join
        # fallback's `not in pre_sids` membership test hashes the sessionId
        # value -- a dict-valued one (CLI drift / hostile roster) raised
        # TypeError instead of being filtered.
        self._hold()
        state = {"name": None}
        def run(argv, **kw):
            if "--bg" in argv:
                state["name"] = next(a for a in argv if a.startswith("sup|"))
                return SimpleNamespace(returncode=0, stdout="launched (no short id token)\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["name"]:
                entries += [
                    {"sessionId": {"nested": "hostile"}, "status": "busy",
                     "name": state["name"]},
                    {"sessionId": "sid-fallback-joined", "status": "busy",
                     "name": state["name"]},
                ]
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        rc = self._begin(run)
        assert rc == 0
        assert "SUCCESSOR-SID: sid-fallback-joined" in capsys.readouterr().out

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

    def test_handoff_begin_doa_writes_abort_flag(self, sup_home, monkeypatch):
        monkeypatch.setattr(fleet, "SUPERVISOR_ROSTER_VERIFY_SECONDS", 0.05)
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=0, stdout="backgrounded · abc · sup\n", stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                [{"sessionId": "sid-old", "status": "busy"}]), stderr="")
        rc = self._begin(run)
        assert rc == 1
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "successor-doa"
        assert flag["successor_sid"] is None
        assert flag["successor_short_id"] == "abc"
        assert flag["holder"] == "inc-old"

    def test_handoff_begin_doa_via_name_fallback_writes_abort_flag(self, sup_home, monkeypatch):
        monkeypatch.setattr(fleet, "SUPERVISOR_ROSTER_VERIFY_SECONDS", 0.05)
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=0, stdout="launched (no short id token)\n", stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                [{"sessionId": "sid-old", "status": "busy"}]), stderr="")
        rc = self._begin(run)
        assert rc == 1
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "successor-doa"
        assert flag["successor_short_id"] is None

    def test_handoff_begin_dispatch_failure_writes_abort_flag(self, sup_home):
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                raise OSError("spawn failed")
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        with pytest.raises(fleet.FleetCliError):
            self._begin(run)
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "dispatch-failed"
        assert flag["successor_sid"] is None
        assert flag["successor_short_id"] is None
        assert flag["holder"] == "inc-old"

    def test_handoff_begin_dispatch_nonzero_exit_writes_abort_flag(self, sup_home):
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        with pytest.raises(fleet.FleetCliError):
            self._begin(run)
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "dispatch-failed"

    def test_handoff_begin_success_leaves_no_abort_flag(self, sup_home):
        self._hold()
        rc = self._begin(self._dispatch_then_roster())
        assert rc == 0
        assert not fleet.handoff_abort_flag_path().exists()

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
        # S1 fix (final wave): routes through _stop_native_session -- tries
        # the SHORT job-ref ("sid", the first hyphen segment) first, not the
        # raw full sid.
        assert stopped and stopped[0][-2:] == ["stop", fleet._native_job_ref("sid-new")]
        assert fleet.read_handshake() is None
        assert fleet.handoff_abort_flag_path().exists()
        assert fleet.supervisor_journal_latest()["kind"] == "HANDOFF-ABORT"
        assert fleet.read_incarnation()["incarnation_id"] == "inc-old"  # old resumes duty

    def test_abort_reports_failed_stop_but_still_flags(self, sup_home, capsys):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-gone")
        def run(argv, **kw):
            return SimpleNamespace(returncode=1, stdout="", stderr="no such session")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-gone")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert fleet.handoff_abort_flag_path().exists()
        assert "stop failed" in capsys.readouterr().out.lower()

    def test_handoff_abort_refuses_on_handshake_sid_mismatch(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-real-successor")
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-WRONG-target")
        with pytest.raises(fleet.FleetCliError, match="does not match HANDSHAKE sid"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run)
        assert not calls   # nothing stopped
        assert not fleet.handoff_abort_flag_path().exists()   # no flag written
        assert fleet.read_handshake() is not None   # handshake untouched
        kinds = [e["kind"] for e in fleet.supervisor_journal_entries()]
        assert "HANDOFF-ABORT" not in kinds

    def test_handoff_abort_proceeds_on_matching_handshake(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-new")
        run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-new")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert fleet.handoff_abort_flag_path().exists()
        assert fleet.read_handshake() is None

    def test_handoff_abort_proceeds_on_absent_handshake_with_matching_flag(self, sup_home):
        # Finding 2 fix: with no HANDSHAKE, the recorded limbo successor in
        # the abort flag (written by sup-handoff-begin on DOA/dispatch-fail)
        # is the only evidence that makes an absent-HANDSHAKE abort legit.
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {
            "aborted_at": fleet.now_iso(), "reason": "successor-doa",
            "successor_sid": "sid-whatever", "successor_short_id": None,
            "holder": "inc-old"})
        run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-whatever")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert fleet.handoff_abort_flag_path().exists()

    def test_handoff_abort_refuses_on_absent_handshake_with_mismatched_flag(self, sup_home):
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {
            "aborted_at": fleet.now_iso(), "reason": "successor-doa",
            "successor_sid": "sid-recorded", "successor_short_id": None,
            "holder": "inc-old"})
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-typo")
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run)
        assert not calls   # nothing stopped

    def test_handoff_abort_refuses_on_absent_handshake_and_no_flag(self, sup_home):
        self._hold()
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-whatever")
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run)
        assert not calls   # nothing stopped

    def test_handoff_abort_refuses_on_none_successor_sid_matching_none_flag(self, sup_home):
        # Roll-up item 8: an abort flag recorded with successor_sid=None
        # (the dispatch-failed shape) must not be treated as matching an
        # args.successor_sid that is itself None -- unreachable via the CLI
        # (argparse required=True) but must refuse, not proceed into
        # `claude stop None`.
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {
            "aborted_at": fleet.now_iso(), "reason": "successor-doa",
            "successor_sid": None, "successor_short_id": None,
            "holder": "inc-old"})
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid=None)
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run)
        assert not calls   # nothing stopped

    def test_begin_clears_previous_abort_flag(self, sup_home):
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {"stale": True})
        self._begin(self._dispatch_then_roster())
        assert not fleet.handoff_abort_flag_path().exists()

    def test_handoff_timeout_drill_end_to_end(self, sup_home):
        """Spec §4 failure branch: begin -> successor never handshakes ->
        complete refuses -> abort stops the limbo successor and old resumes.

        Post-Finding-2-fix: the roster join succeeded here, so begin's DOA/
        dispatch-failure abort-flag paths never fire and HANDSHAKE is never
        written (that's the whole point of the drill). Under the new
        absent-HANDSHAKE rule, abort itself now needs recorded evidence
        before it will act -- simulate the operator recording the sid
        printed as SUCCESSOR-SID by begin (external verification is the
        documented alternative when no flag exists, per the abort
        docstring)."""
        self._hold()
        rc = self._begin(self._dispatch_then_roster())
        assert rc == 0
        args = SimpleNamespace(sid="sid-old",
                               expect_inc="inc-whatever", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):   # no HANDSHAKE was written
            fleet.cmd_sup_handoff_complete(args)
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {
            "aborted_at": fleet.now_iso(), "reason": "operator-recorded",
            "successor_sid": "sid-new", "successor_short_id": None,
            "holder": "inc-old"})
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


class TestDispatchPathsAreDocumented:
    """Defect A regression: SPEC §6 claimed "one choke point for every --bg
    launch" while `bin/fleet.py` has always had TWO argv builders. The claim is
    now scoped to worker launches and the second path is named; these tests go
    RED if either the code grows a third path or the SPEC text drops the
    correction."""

    REPO = Path(__file__).resolve().parents[1]
    # B3 + G1: the guard SPEC §6.1 leans on has been evaded twice. It began as
    # `r'^\s*argv = \[exe, "--bg"'` -- one spelling -- and injection I16 walked
    # past it with `cmd = [claude_exe, "--bg", ...]`. The B3 widening to
    # `r'\[[^\]\n]*"--bg"'` still could not cross a newline, so a builder whose
    # list literal wraps (`argv = [\n    exe, "--bg", ...`) walked past that.
    # Dropping the newline exclusion catches every spelling; verified still
    # exactly 2 on the real source, and 3 under each evasion in
    # `test_shape_guard_catches_every_third_builder_spelling`.
    ARGV_BUILDER_RE = re.compile(r'\[[^\]]*"--bg"')
    # Every builder that legitimately exists, by the function that owns it.
    KNOWN_BUILDERS = ("dispatch_bg", "cmd_sup_handoff_begin")

    def _source(self):
        return (self.REPO / "bin" / "fleet.py").read_text(encoding="utf-8")

    def _spec(self):
        return (self.REPO / "docs" / "SPEC.md").read_text(encoding="utf-8")

    def _section(self):
        spec = self._spec()
        return spec.split("## 6. Dispatch contract", 1)[1].split("\n## 7.", 1)[0]

    def _subsection_61(self):
        """D3: §6.1 ONLY. `_section()` spans §6 through §7, and §6's own lead
        sentence and argv block already contain `cmd_sup_handoff_begin` and
        `--settings` -- so a test asserting those against `_section()` stayed
        green when the reviewer deleted §6.1 wholesale, while SPEC §6.1 claimed
        the test 'fails if this subsection stops naming the path'. A spec
        sentence asserting protection that does not exist is worse than none."""
        return self._section().split("### 6.1", 1)[1]

    def test_exactly_two_bg_argv_builders(self):
        """Not a fix pin -- a shape guard. A THIRD argv builder means the
        SPEC's enumeration is stale again and must be extended."""
        assert len(self.ARGV_BUILDER_RE.findall(self._source())) == 2

    @pytest.mark.parametrize("label,builder", [
        ("plain", '\ndef _third(exe):\n    argv = [exe, "--bg", "-n", "p"]\n    return argv\n'),
        ("renamed", '\ndef _third(x):\n    cmd = [x, "--bg", "-n", "p"]\n    return cmd\n'),
        ("augmented", '\ndef _third(exe):\n    argv = [exe]\n    argv += ["--bg", "-n", "p"]\n    return argv\n'),
        ("multiline", '\ndef _third(exe):\n    argv = [\n        exe, "--bg",\n        "-n", "p",\n    ]\n    return argv\n'),
    ])
    def test_shape_guard_catches_every_third_builder_spelling(self, label, builder):
        """G1: this guard has now been evaded twice -- B3 (`cmd = [claude_exe,`
        walked past the `argv = [exe,` spelling) and G1 (a builder whose list
        literal wraps across a newline walked past `[^\\]\\n]*`). It is the guard
        SPEC §6.1 leans on to keep the dispatch enumeration from going stale a
        second time, so every spelling a real third builder could take is
        pinned here rather than discovered by the next reviewer."""
        source = self._source()
        assert len(self.ARGV_BUILDER_RE.findall(source)) == 2, "baseline"
        assert len(self.ARGV_BUILDER_RE.findall(source + builder)) == 3, label

    def test_both_bg_argv_builders_live_in_the_documented_functions(self):
        """B3, the other half: two builders is only reassuring if they are the
        two §6.1 names. A third builder that REPLACED one of these would keep
        the count at 2."""
        source = self._source()
        owners = []
        for m in self.ARGV_BUILDER_RE.finditer(source):
            head = source[:m.start()]
            defs = re.findall(r"^def (\w+)", head, re.M)
            owners.append(defs[-1] if defs else None)
        assert sorted(owners) == sorted(self.KNOWN_BUILDERS)

    def test_spec_lead_sentence_scopes_the_choke_point(self):
        """The pre-fix lead read 'Every native launch ... funnels through one
        choke point', which is false: the successor never did. It must now
        scope to WORKER launches and say how many builders exist."""
        # drop the remainder of the "## 6. Dispatch contract ..." heading line
        body = self._section().split("\n", 1)[1]
        lead = next(l for l in body.splitlines() if l.strip()).lower()
        assert "worker" in lead
        assert "two" in lead and "argv builder" in lead

    def test_spec_names_the_successor_dispatch_path(self):
        """D3: asserted against §6.1 alone, and against the tokens that carry
        the subsection's load -- so deleting or hollowing it goes RED."""
        sub = self._subsection_61()
        assert "cmd_sup_handoff_begin" in sub
        for token in ("--settings", "_worker_env", "_require_instance_settings",
                      "supervisor-handoff-", "NAME_RE"):
            assert token in sub, token

    def test_spec_61_records_the_mode_flag_decision(self):
        """B4/D6: §6.1's parity enumeration claimed the path carries what the
        choke point carries and listed two deliberate omissions, silently
        omitting the third and only hazardous asymmetry."""
        sub = self._subsection_61()
        assert "mode" in sub.lower()
        assert "SUCCESSOR_DEFAULT_MODE" in sub

    def test_spec_61_keeps_the_unobserved_hedge(self):
        """D7: the branch's own docstring and commit message hedge the daemon
        env-propagation claim; the SPEC stated it flatly. The spec is the
        artifact a future builder trusts -- it must be the more careful one."""
        sub = self._subsection_61()
        assert "UNVERIFIED" in sub or "UNOBSERVED" in sub

    def test_spec_12_does_not_claim_the_successor_uses_dispatch_bg(self):
        """D2: §12 still read 'old dispatches a claim-pending successor via
        `dispatch_bg`' -- false, and false in the same document whose §6.1
        exists to explain why it cannot be `dispatch_bg`. The branch corrected
        §6 and left the other half of the same inaccuracy standing."""
        spec = self._spec()
        section12 = spec.split("## 12. Supervisor protocol", 1)[1].split("\n## 13.", 1)[0]
        assert "via `dispatch_bg`" not in section12
        assert "§6.1" in section12


class TestOperatorGatesBriefing:
    """The operator asked (2026-07-21) that ratification decisions be put to
    them BEFORE a session starts any work. A doc paragraph cannot enforce
    that; the SessionStart hook can, because it injects context into every
    manager session automatically. These pin the mechanism.

    Read-only, tolerate-and-ignore, exit 0 -- the hook's standing invariants.
    A gate that fails to surface is a missed prompt; a hook that raises is a
    broken session start."""

    def _hook(self, monkeypatch):
        import importlib.util
        hook_path = (fleet.Path(fleet.__file__).resolve().parent / "hooks"
                     / "sessionstart_fleet.py")
        spec = importlib.util.spec_from_file_location("sessionstart_fleet", hook_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "fleet", fleet)
        return mod

    def _seed(self, sup_home):
        (sup_home / "state" / "fleet.json").write_text(
            json.dumps({"workers": {}}), encoding="utf-8")
        docs = sup_home / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        return docs / "OPERATOR-GATES.md"

    def test_open_gates_lead_the_briefing(self, sup_home, monkeypatch):
        gates = self._seed(sup_home)
        gates.write_text(
            "# Operator gates\n\n## Open\n\n"
            "- [ ] **Ratify the contract rows** — ratify, reject, or ask for evidence?\n"
            "- [x] **Already settled** — answered 2026-01-01.\n",
            encoding="utf-8")
        ctx = self._hook(monkeypatch)._build_context()
        assert ctx.startswith("OPERATOR GATES: 1 decision(s)"), ctx[:200]
        assert "ASK THESE FIRST" in ctx
        assert "Ratify the contract rows" in ctx
        # a ticked gate is history, never re-surfaced
        assert "Already settled" not in ctx
        # and the rest of the briefing still lands, below them
        assert ctx.index("OPERATOR GATES") < ctx.index("FLEET:")

    def test_no_open_gates_means_no_banner(self, sup_home, monkeypatch):
        gates = self._seed(sup_home)
        gates.write_text("# Operator gates\n\n## Settled\n\n- [x] done — 2026-01-01.\n",
                         encoding="utf-8")
        ctx = self._hook(monkeypatch)._build_context()
        assert "OPERATOR GATES" not in ctx
        assert "FLEET:" in ctx

    def test_missing_or_unreadable_file_degrades_silently(self, sup_home, monkeypatch):
        self._seed(sup_home)  # no OPERATOR-GATES.md written at all
        mod = self._hook(monkeypatch)
        assert mod._operator_gate_lines() == []
        ctx = mod._build_context()
        assert "OPERATOR GATES" not in ctx
        assert "FLEET:" in ctx

    def test_the_shipped_gates_file_parses_and_has_open_items(self):
        """The real docs/OPERATOR-GATES.md must actually drive the hook -- a
        format drift here silently empties the ask-first queue, which is the
        one failure mode the operator would never see."""
        repo = Path(__file__).resolve().parents[1]
        text = (repo / "docs" / "OPERATOR-GATES.md").read_text(encoding="utf-8")
        open_gates = [ln for ln in text.splitlines() if ln.strip().startswith("- [ ]")]
        assert open_gates, "no open gates parse out of the shipped file"
        for ln in open_gates:
            assert ln.strip().endswith("?"), f"a gate must be a question: {ln[:80]}"
