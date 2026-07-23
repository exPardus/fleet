"""three-tier-command.md §8 -- operator-gate routing as a STATE FILE.

A background supervisor must route operator-only decisions (destructive ops,
HALT ratification, GOALS edits, spec promotion) to the interface tier and PARK,
never self-approve. §8's design: `state/supervisor-pending-decision.json` --
answerable, un-re-derivable (its PRESENCE is the open state, not a journal
scan), nag-visible (doctor + sup-status), one open decision at a time. The
supervisor RAISES (claim-holder gated); the interface ANSWERS (unclaimed, since
the interface holds no claim by design); the file is CLEARED when consumed.

The withdrawn PROPOSAL's `NEEDS-OPERATOR` journal kind is rejected here (§8): a
journal is append-only and cannot be *cleared*, so it cannot represent an
open-then-answered decision.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def dec_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor"):
        (tmp_path / sub).mkdir()
    return tmp_path


def _fresh_claim(sid="sid-sup", beat_age_seconds=5, **extra):
    beat = (datetime.now(timezone.utc)
            - timedelta(seconds=beat_age_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    value = fleet.mint_nonce()
    claim = {"incarnation_id": "inc-me", "session_id": sid,
             "claimed_at": beat, "heartbeat_at": beat, "claimed_via": "fresh",
             "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 3,
             "lineage_id": "lin-L"}
    claim.update(extra)
    fleet.write_incarnation(claim)
    return value


def _raise_args(question="Delete prod DB?", context_ref="brief.md#L4",
                sid="sid-sup", nonce=None):
    return SimpleNamespace(question=question, context_ref=context_ref,
                           answer=None, clear=False, json=False,
                           sid=sid, nonce=nonce)


class TestStateFileModel:
    def test_read_returns_none_when_absent(self, dec_home):
        assert fleet.read_pending_decision() is None

    def test_write_then_read_roundtrips(self, dec_home):
        fleet.write_pending_decision({"question": "q", "answer": None})
        assert fleet.read_pending_decision()["question"] == "q"

    def test_corrupt_file_reads_as_unreadable_not_absent(self, dec_home):
        # A corrupt pending-decision file must stay NAG-VISIBLE, never silently
        # read as "no decision open" (that would drop an operator gate).
        fleet.pending_decision_path().write_text("{not json", encoding="utf-8")
        rec = fleet.read_pending_decision()
        assert rec is not None and rec.get("_unreadable") is True

    def test_clear_removes_the_file(self, dec_home):
        fleet.write_pending_decision({"question": "q"})
        fleet.clear_pending_decision()
        assert fleet.read_pending_decision() is None

    def test_clear_is_idempotent(self, dec_home):
        fleet.clear_pending_decision()  # nothing to clear -- must not raise


class TestRaise:
    def test_supervisor_raises_a_decision(self, dec_home, monkeypatch):
        nonce = _fresh_claim()
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        rc = fleet.cmd_sup_decision(_raise_args(nonce=nonce))
        assert rc == 0
        rec = fleet.read_pending_decision()
        assert rec["question"] == "Delete prod DB?"
        assert rec["raised_by_inc"] == "inc-me"
        assert rec["context_ref"] == "brief.md#L4"
        assert rec["answer"] is None
        assert rec["raised_at"]

    def test_raise_requires_the_claim_holder(self, dec_home, monkeypatch):
        _fresh_claim(sid="sid-sup")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-other")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_decision(_raise_args(sid="sid-other", nonce=None))

    def test_only_one_open_decision_at_a_time(self, dec_home, monkeypatch):
        # An open (unanswered) decision already exists; the holder presents a
        # VALID generation (so continuity passes) and still gets refused --
        # isolating the one-at-a-time guard from the continuity gate ahead of it.
        nonce = _fresh_claim()
        fleet.write_pending_decision({"question": "first?", "raised_by_inc": "inc-me",
                                      "raised_at": fleet.now_iso(), "answer": None})
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        with pytest.raises(fleet.FleetCliError, match="already open"):
            fleet.cmd_sup_decision(_raise_args(question="another?", nonce=nonce))

    def test_a_new_decision_may_be_raised_once_the_prior_is_answered(
            self, dec_home, monkeypatch):
        # An ANSWERED-but-not-cleared decision does not block a new raise (the
        # guard keys on unanswered-open, not mere presence).
        nonce = _fresh_claim()
        fleet.write_pending_decision({"question": "first?", "raised_by_inc": "inc-me",
                                      "raised_at": fleet.now_iso(), "answer": "yes",
                                      "answered_at": fleet.now_iso()})
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        assert fleet.cmd_sup_decision(_raise_args(question="second?", nonce=nonce)) == 0
        assert fleet.read_pending_decision()["question"] == "second?"


class TestAnswer:
    def test_interface_answers_without_a_claim(self, dec_home, monkeypatch):
        # The interface tier holds NO claim (§3.1) -- answering must not require
        # continuity. It writes the operator's decision into `answer`.
        fleet.write_pending_decision({"question": "q", "raised_by_inc": "inc-me",
                                      "raised_at": fleet.now_iso(), "answer": None})
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        args = SimpleNamespace(question=None, context_ref=None, answer="No -- keep it",
                               clear=False, json=False, sid=None, nonce=None)
        rc = fleet.cmd_sup_decision(args)
        assert rc == 0
        rec = fleet.read_pending_decision()
        assert rec["answer"] == "No -- keep it"
        assert rec["answered_at"]

    def test_answer_with_no_open_decision_errors(self, dec_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        args = SimpleNamespace(question=None, context_ref=None, answer="x",
                               clear=False, json=False, sid=None, nonce=None)
        with pytest.raises(fleet.FleetCliError, match="no open decision"):
            fleet.cmd_sup_decision(args)

    def test_clear_via_verb(self, dec_home, monkeypatch):
        fleet.write_pending_decision({"question": "q", "answer": "done"})
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        args = SimpleNamespace(question=None, context_ref=None, answer=None,
                               clear=True, json=False, sid=None, nonce=None)
        assert fleet.cmd_sup_decision(args) == 0
        assert fleet.read_pending_decision() is None


class TestNagSurfaces:
    def test_doctor_fails_on_open_unanswered_decision(self, dec_home):
        fleet.write_pending_decision({"question": "Delete prod DB?",
                                      "raised_by_inc": "inc-me",
                                      "raised_at": fleet.now_iso(), "answer": None})
        name, ok, msg = fleet._doctor_check_pending_decision()
        assert name == "supervisor-pending-decision"
        assert ok is False
        assert "Delete prod DB?" in msg

    def test_doctor_passes_with_no_decision(self, dec_home):
        name, ok, msg = fleet._doctor_check_pending_decision()
        assert ok is True

    def test_doctor_notes_but_passes_an_answered_decision(self, dec_home):
        fleet.write_pending_decision({"question": "q", "raised_by_inc": "inc-me",
                                      "raised_at": fleet.now_iso(),
                                      "answer": "yes", "answered_at": fleet.now_iso()})
        name, ok, msg = fleet._doctor_check_pending_decision()
        assert ok is True
        assert "answered" in msg.lower()

    def test_doctor_fails_on_corrupt_file(self, dec_home):
        fleet.pending_decision_path().write_text("{bad", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_pending_decision()
        assert ok is False

    def test_sup_status_json_carries_pending_decision(self, dec_home):
        fleet.write_pending_decision({"question": "q", "raised_by_inc": "inc-me",
                                      "raised_at": fleet.now_iso(), "answer": None})
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fleet.cmd_sup_status(SimpleNamespace(json=True))
        info = json.loads(buf.getvalue())
        assert info["pending_decision"]["question"] == "q"

    def test_sup_status_json_null_when_no_decision(self, dec_home):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fleet.cmd_sup_status(SimpleNamespace(json=True))
        info = json.loads(buf.getvalue())
        assert info["pending_decision"] is None
