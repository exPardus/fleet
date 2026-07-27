"""The stillborn-supervisor-handoff incident, 2026-07-24 .. 2026-07-27.

For three days every `fleet sup-handoff-begin` run under its DEFAULT mode
dispatched a successor that never booted. Three supervisor incarnations chased
it; a read-only autopsy closed it by measurement over `state/events.jsonl`
`spawned` events plus six transcripts read directly:

    dispatched mode | successors | outcome
    bypass          | 7          | all booted, all handoffs completed
    dontask         | 10         | all stillborn, 2 x permission-rule denial,
                                   dead in 25-33 s

17/17, zero exceptions. Three separate defects made those three days possible
and this file pins one behaviour per defect.

  A  THE CAUSE. `SUCCESSOR_DEFAULT_MODE` was `dontask`, so the successor was
     dispatched with `--permission-mode dontAsk`, and its FIRST act is a Bash
     call (`fleet sup-boot`) that no allow-list covers. `dontAsk` does not
     prompt -- it DENIES -- so the body died before it could boot. The 2026-07-21
     reasoning behind that default was about HANGS, was correct about hangs, and
     was never tested against a command outside the allow-list.

  B  WHY IT STAYED INVISIBLE. `cmd_sup_handoff_begin` filed the successor's
     registry record with `session_id=None` while the joined sid was in hand and
     about to be printed. Hooks resolve a worker name by scanning the registry
     for `session_id == sid`, so every successor's Stop outcome was written to
     `state/outcomes/<raw-sid>.jsonl`, where `read_outcomes(name)` never looks.
     The stillborn successors stated their own diagnosis out loud on day one and
     nothing on the fleet side could hear it. Same block, same class: `turns`
     was never stamped either, so a running successor rendered as `working,
     0 turns` -- and that reading was then cited as proof that no session had
     ever launched.

  C  THE LIE THAT MISLED THREE SUPERVISORS. `_cmd_peek_native` answered a null
     `session_id` with "no transcript yet -- dispatch may still be in flight".
     The transcripts existed two seconds after dispatch (82KB, 26-27 messages,
     Stop hooks fired clean). A RECORD-SHAPE fact was rendered as a TIMING
     claim, and a predecessor believed it for 17 minutes.

PIN DESIGN. `assert SUCCESSOR_DEFAULT_MODE == "bypass"` would be a tautology --
it restates the line it guards and survives any future edit that changes both
places. Every pin here asserts the OBSERVABLE the incident actually turned on:
the flags on the dispatch argv, the file the outcome lands in, the sentence the
operator reads. Each has been watched RED against its own defect reverted.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet

REPO_ROOT = Path(__file__).resolve().parents[1]
STOP_OUTCOME = REPO_ROOT / "bin" / "hooks" / "stop_outcome.py"

SUCC_SID = "succ0001-full"
SUCC_SHORT = "succ0001"


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME, same shape as tests/test_handoff_seams.py's."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n",
                                  encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- entry one\n",
                                                     encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}',
                                                             encoding="utf-8")
    return tmp_path


def _fake_which(_name):
    return "C:/fake/claude.cmd"


def _hold(sid="sid-old", inc="inc-old"):
    fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                             "claimed_at": "2026-07-14T12:00:00Z",
                             "heartbeat_at": "2026-07-14T12:00:00Z",
                             "claimed_via": "fresh"})


def _dispatch_then_roster(calls):
    """Stateful `subprocess.run` double recording every argv: the successor
    appears in the roster only after the `--bg` dispatch is observed (the
    contract G6 short-id join)."""
    state = {"dispatched": False}

    def run(argv, **kw):
        calls.append(argv)
        if "--bg" in argv:
            state["dispatched"] = True
            return SimpleNamespace(returncode=0,
                                   stdout=f"backgrounded \u00b7 {SUCC_SHORT} \u00b7 sup\n",
                                   stderr="")
        entries = [{"sessionId": "sid-old", "status": "busy"}]
        if state["dispatched"]:
            entries.append({"sessionId": SUCC_SID, "status": "busy"})
        return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")

    return run


def _begin(run, permission_mode=None, model=None):
    args = SimpleNamespace(sid="sid-old", model=model,
                           permission_mode=permission_mode)
    return fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                       sleep=lambda s: None)


def _successor_record(sup_home):
    """(name, record) of the one successor row `begin` filed."""
    data = json.loads((sup_home / "state" / "fleet.json").read_text(encoding="utf-8"))
    rows = [(n, r) for n, r in data["workers"].items() if n.endswith("|successor")]
    assert len(rows) == 1, f"expected exactly one successor row, got {list(data['workers'])}"
    return rows[0]


# ---------------------------------------------------------------------------
# A -- the cause: the dispatched successor must be able to run its own bootstrap
# ---------------------------------------------------------------------------

class TestTheSuccessorIsDispatchedUnderAModeThatCanRunItsBootstrap:
    def test_the_default_dispatch_argv_carries_bypass_permission_flags(self, sup_home):
        """The pin is on the ARGV, deliberately, and never on the constant.

        `assert fleet.SUCCESSOR_DEFAULT_MODE == "bypass"` restates the line it
        guards: it passes against whatever a future editor sets that line to,
        as long as they edit the test too. This asserts the literal flag that
        actually reaches the launched process, so it fails BOTH when the
        constant reverts (`dontask` renders `--permission-mode dontAsk`) AND
        when a refactor stops the constant from reaching the command line at
        all -- which is the failure mode that will really happen, because this
        dispatch does not go through `dispatch_bg` and has no other guard."""
        _hold()
        calls = []
        assert _begin(_dispatch_then_roster(calls)) == 0
        dispatch = next(c for c in calls if "--bg" in c)
        assert "--dangerously-skip-permissions" in dispatch, dispatch

    def test_the_default_dispatch_never_carries_the_denying_mode(self, sup_home):
        """The specific harm, stated as itself: `dontAsk` auto-DENIES anything
        the allow-list does not already cover, and the successor's first act is
        `fleet sup-boot` through Bash. Ten successors were dispatched this way
        and all ten died at that call. Any spelling of it on this argv is the
        incident."""
        _hold()
        calls = []
        assert _begin(_dispatch_then_roster(calls)) == 0
        dispatch = next(c for c in calls if "--bg" in c)
        assert "dontAsk" not in dispatch, dispatch
        assert "--permission-mode" not in dispatch, dispatch

    def test_the_successor_record_stores_the_mode_it_was_dispatched_under(self, sup_home):
        """`SUCCESSOR_DEFAULT_MODE` has THREE code readers, not one: the argv
        (above), this registry field, and the `--help` default. A fix applied
        to the dispatch alone would leave `fleet status` reporting a mode the
        successor is not running under -- exactly the class of accounting lie
        defect B is."""
        _hold()
        assert _begin(_dispatch_then_roster([])) == 0
        _name, rec = _successor_record(sup_home)
        assert rec["mode"] == "bypass"

    def test_an_explicit_permission_mode_still_wins(self, sup_home):
        """The fix must not become a policy the operator cannot override."""
        _hold()
        calls = []
        assert _begin(_dispatch_then_roster(calls), permission_mode="plan") == 0
        dispatch = next(c for c in calls if "--bg" in c)
        assert dispatch[dispatch.index("--permission-mode") + 1] == "plan"
        assert "--dangerously-skip-permissions" not in dispatch


# ---------------------------------------------------------------------------
# B -- the silence: the record must carry the sid that was in hand
# ---------------------------------------------------------------------------

class TestTheSuccessorRecordCarriesTheSidBeginAlreadyHas:
    def test_the_record_carries_the_sid_that_begin_prints(self, sup_home, capsys):
        """The record was filed with `session_id=None` on the very lines that
        print `SUCCESSOR-SID:`. Asserted against the PRINTED value rather than
        the fixture constant, so the two can never drift apart silently."""
        _hold()
        assert _begin(_dispatch_then_roster([])) == 0
        out = capsys.readouterr().out
        printed = next(l.split(": ", 1)[1].strip() for l in out.splitlines()
                       if l.startswith("SUCCESSOR-SID:"))
        _name, rec = _successor_record(sup_home)
        assert rec["session_id"] == printed

    def test_the_stop_hook_files_the_successors_outcome_where_the_fleet_reads_it(
            self, sup_home):
        """THE HARM ITSELF, end to end, through the real hook in a real
        subprocess.

        `stop_outcome.py::_resolve_name` scans the registry for
        `session_id == sid`. With the record sid-less it missed, fell back to
        `key = sid`, and wrote `state/outcomes/<raw-sid>.jsonl` -- a path
        `read_outcomes(name)` never opens. That is why ten successors could
        each state their own diagnosis and leave no trace the fleet could
        surface: `fleet result <successor>` had nothing to read.

        A pin on `session_id is not None` alone would pass while the outcome
        still landed in the wrong file (e.g. if the resolver's match key ever
        changed), so this asserts the FILE and the READ, not the field."""
        _hold()
        assert _begin(_dispatch_then_roster([])) == 0
        name, rec = _successor_record(sup_home)
        sid = rec["session_id"]

        env = dict(os.environ)
        env["FLEET_HOME"] = str(sup_home)
        proc = subprocess.run(
            [sys.executable, str(STOP_OUTCOME)],
            input=json.dumps({"session_id": sid,
                              "last_assistant_message": "Blocked. Cannot start."}),
            capture_output=True, text=True, env=env, timeout=15)
        assert proc.returncode == 0, proc.stderr
        assert not (sup_home / "logs" / "hook-errors.log").exists()

        outcomes = sup_home / "state" / "outcomes"
        assert (outcomes / f"{fleet.name_fs_stem(name)}.jsonl").exists()
        assert not (outcomes / f"{sid}.jsonl").exists(), (
            "the outcome was filed under the raw sid -- the orphaned-file defect")
        recs = fleet.read_outcomes(name)
        assert [r["result_text"] for r in recs] == ["Blocked. Cannot start."]

    def test_the_successor_record_counts_its_first_turn(self, sup_home):
        """The FOURTH observable, and the one that actively misled: the
        registry reported these sessions as `working` with **0 turns**, and
        "0 turns" was then used as evidence that no session had ever run.

        It is a registry accounting defect, not a fact. Every other dispatch
        commit in fleet.py stamps `turns = 1` at the moment it stamps the sid
        (`cmd_spawn`, `cmd_respawn`, `send`'s fresh-session path,
        `cmd_sup_spawn`); this block is a fourth dispatch site and stamped
        neither. Nothing recomputes `turns` from outcomes afterwards, so a
        successor that never got it here never got it at all.

        NOTE for a future reader: fixing the sid alone does NOT fix this. The
        two are separate omissions in the same block."""
        _hold()
        assert _begin(_dispatch_then_roster([])) == 0
        _name, rec = _successor_record(sup_home)
        assert rec["status"] == "working"
        assert rec["turns"] == 1, (
            "a dispatched, roster-verified successor rendered as 'working, "
            "0 turns' -- the reading three supervisors mistook for 'never ran'")


# ---------------------------------------------------------------------------
# C -- the lie: a record-shape fact must not be rendered as a timing claim
# ---------------------------------------------------------------------------

class TestPeekDoesNotTurnANullSidIntoATimingVerdict:
    def test_a_sidless_peek_states_the_record_fact_it_actually_read(self, sup_home, capsys):
        """`_cmd_peek_native` has read ONE field and knows ONE thing: this
        record's `session_id` is null. That is what it must say."""
        assert fleet._cmd_peek_native("w1", None, 20) == 1
        err = capsys.readouterr().err
        assert "no session id" in err.lower()

    def test_a_sidless_peek_does_not_assert_that_the_dispatch_is_in_flight(
            self, sup_home, capsys):
        """The defect was not the wording, it was the CLAIM. "no transcript yet
        -- dispatch may still be in flight" asserts a cause this function
        cannot know, and it picked the reassuring one: the transcripts existed
        two seconds after dispatch, 82KB of them, while `peek` said this for 17
        minutes.

        Pinned as a property rather than as a string match, so a reworded
        single-cause sentence goes RED too: if the output offers `in flight` at
        all, it must also offer the readings that are NOT reassuring."""
        assert fleet._cmd_peek_native("w1", None, 20) == 1
        err = capsys.readouterr().err
        assert "no transcript yet" not in err
        if "in flight" in err:
            assert "failed" in err, err
            assert "never recorded" in err, err

    def test_the_resolvable_sid_paths_are_untouched(self, sup_home, capsys):
        """C is scoped to the `sid is None` arm. A record WITH a sid whose
        transcript is genuinely absent is a different fact and keeps its own
        distinct message -- collapsing the two would trade one lie for
        another."""
        fleet._cmd_peek_native("w1", "sid-real", 20)
        err = capsys.readouterr().err
        assert "no session id" not in err.lower()
        assert "sid-real" in err
