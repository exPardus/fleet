"""Cut 1 (w87, `docs/lanes/w87.md`): an idle supervisor body's wake must
resume the SAME incarnation on a fresh, unforked `--bg` dispatch -- never
`--bg --resume <sid>`, which the vendor forks (G2, `docs/specs/
native-substrate.md`) into a new sid carrying the full prior transcript and
leaves the old sid as a `blocked`/no-pid roster corpse
(`state/tasks/20260915-guard-blocked-corpses.md`).

Two things are pinned:
* `test_idle_supervisor_wakes_without_forking` -- the dispatch itself never
  carries `--resume`, the worker record is restamped (not fork-retired into
  a parallel identity), and the task file points the fresh body at
  `sup-boot --nonce <token>`, never at a resumed transcript.
* `test_wake_token_lets_a_fresh_body_resume_the_same_incarnation` -- the
  credential the wake mints is not decorative: driven through the REAL
  (unmocked) `cmd_sup_boot`/`supervisor_claim_decision` code, a fresh body
  presenting it gets verdict `resume` for the SAME incarnation_id, never a
  new one -- proving this is a wake, not a disguised handoff.

Refusal-path tests cover a claim that changed underneath the wake decision
(a concurrent handoff/seizure/release): the dispatch must never fire, and
both the mailbox and the registry pre-claim must roll back exactly as the
ordinary fork-steer path already does on failure.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
OLD_SID = "aaaabbbb-1111-2222-3333-444455556666"
NEW_SID = "ccccdddd-9999-8888-7777-666655554444"
NAME = "sup|inc-wtest|boot"
INC = "inc-wtest"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def wake_home(tmp_path, monkeypatch):
    """FLEET_HOME with everything both `cmd_send` (native dispatch) and
    `cmd_sup_boot` (claim decision + boot bundle) need."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- entry one\n",
                                                      encoding="utf-8")
    return tmp_path


def _seed_supervisor_worker(home, *, sid=OLD_SID, status="idle"):
    rec = fleet.new_worker_record(sid, str(home), "supervisor duty", "bypass",
                                  dispatch_kind="bg")
    rec["status"] = status
    rec["native_short_id"] = sid[:8]
    rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
    fleet.save_registry({"workers": {NAME: rec}})
    return rec


def _seed_claim(*, incarnation_id=INC, session_id=OLD_SID, extra=None):
    claim = {"incarnation_id": incarnation_id, "session_id": session_id,
             "claimed_at": _iso(NOW - timedelta(hours=1)),
             "heartbeat_at": _iso(NOW - timedelta(minutes=6)),
             "claimed_via": "fresh", "nonce_hash": "deadbeef" * 4, "nonce_seq": 1}
    if extra:
        claim.update(extra)
    fleet.write_incarnation(claim)
    return claim


def _roster_sequence(*results):
    state = {"n": 0}

    def fetch(**_):
        i = min(state["n"], len(results) - 1)
        state["n"] += 1
        return results[i]
    return fetch


def _make_roster_entry(sid, *, status="idle", state="done", pid=None):
    entry = {"id": sid[:8], "sessionId": sid, "name": NAME, "cwd": "C:/proj",
             "startedAt": 1783986489446, "kind": "background", "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    return entry


def _fake_dispatch_run(new_sid=NEW_SID, calls=None):
    def run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        import types
        return types.SimpleNamespace(
            returncode=0, stdout=f"backgrounded \xb7 {new_sid[:8]} \xb7 {NAME}\n", stderr="")
    return run


def _send_args(message="wake up"):
    return SimpleNamespace(name=NAME, message=message)


def _events_kinds(home):
    path = home / "state" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln)["kind"] for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


class TestIdleSupervisorWake:
    def test_idle_supervisor_wakes_without_forking(self, wake_home, monkeypatch, capsys):
        _seed_supervisor_worker(wake_home, sid=OLD_SID, status="idle")
        fleet.append_outcome(NAME, {"ts": _iso(NOW), "session_id": OLD_SID, "kind": "result"})
        _seed_claim()
        calls = []
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []),                                             # cmd_send's own verdict fetch
            (True, []),                                             # dispatch_bg pre-dispatch snapshot
            (True, [_make_roster_entry(NEW_SID, status="idle", state="working")]),  # join poll
        ))

        rc = fleet.cmd_send(_send_args(message="wake up, please"),
                            run=_fake_dispatch_run(calls=calls),
                            which=lambda _: "claude", sleep=lambda s: None)

        assert rc == 0
        rec = fleet.load_registry()["workers"][NAME]
        assert rec["session_id"] == NEW_SID
        assert OLD_SID in rec["retired_sids"]
        assert rec["status"] == "working"
        assert rec["turns"] == 1

        assert len(calls) == 1, calls
        assert "--resume" not in calls[0]

        task = fleet.task_file_path(NAME).read_text(encoding="utf-8")
        assert "sup-boot" in task and "--nonce" in task
        assert "wake up, please" in task

        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == INC          # unchanged: no new generation
        assert claim.get("pending_nonce_hash")          # a wake credential was minted

        out = capsys.readouterr().out
        assert "woken" in out
        assert "fork-steered" not in out
        assert "fork carries full transcript" not in out

        events = set(_events_kinds(wake_home))
        assert "woken" in events
        assert "steered" not in events

        assert not (fleet.mailbox_dir() / f"{OLD_SID}.md").exists()

    def test_wake_token_lets_a_fresh_body_resume_the_same_incarnation(
            self, wake_home, monkeypatch):
        """The credential is not decorative: drive the REAL sup-boot claim
        decision with it and confirm verdict=resume, same incarnation_id --
        this is what distinguishes a wake from a disguised handoff/seizure.
        """
        _seed_supervisor_worker(wake_home, sid=OLD_SID, status="idle")
        fleet.append_outcome(NAME, {"ts": _iso(NOW), "session_id": OLD_SID, "kind": "result"})
        _seed_claim()
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []), (True, []),
            (True, [_make_roster_entry(NEW_SID, status="idle", state="working")]),
        ))

        rc = fleet.cmd_send(_send_args(), run=_fake_dispatch_run(),
                            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0

        task = fleet.task_file_path(NAME).read_text(encoding="utf-8")
        wake_nonce = re.search(r"--nonce (\S+)", task).group(1)

        def boot_roster_run(argv, **kw):
            assert "--json" in argv and "--all" in argv
            import json as _json
            entries = [_make_roster_entry(NEW_SID, status="idle", state="working")]
            return SimpleNamespace(returncode=0, stdout=_json.dumps(entries), stderr="")

        boot_rc = fleet.cmd_sup_boot(
            SimpleNamespace(sid=NEW_SID, handoff_inc=None, nonce=wake_nonce),
            which=lambda _: "C:/fake/claude.cmd", run=boot_roster_run)
        assert boot_rc == 0

        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == INC           # SAME generation, never a new one
        assert claim["session_id"] == NEW_SID            # restamped by sup-boot's own resume verdict

    def test_ordinary_worker_still_forks(self, wake_home, monkeypatch):
        """Regression guard for Cut 1's scope: an ordinary (non-supervisor)
        idle worker keeps the ratified G2b fork-steer -- only supervisor-
        shaped bodies get the wake path."""
        name = "w1"
        rec = fleet.new_worker_record(OLD_SID, str(wake_home), "do the thing", "accept",
                                      dispatch_kind="bg")
        rec["status"] = "idle"
        rec["native_short_id"] = OLD_SID[:8]
        rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
        fleet.save_registry({"workers": {name: rec}})
        fleet.append_outcome(name, {"ts": _iso(NOW), "session_id": OLD_SID, "kind": "result"})
        calls = []
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []), (True, []),
            (True, [{"id": NEW_SID[:8], "sessionId": NEW_SID, "name": f"fleet|{name}|t",
                     "cwd": "C:/proj", "startedAt": 1, "kind": "background",
                     "state": "working", "status": "idle", "pid": 1}]),
        ))
        rc = fleet.cmd_send(SimpleNamespace(name=name, message="go"),
                           run=_fake_dispatch_run(calls=calls),
                           which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        assert any("--resume" in c for c in calls)


class TestWakeRefusesOnChangedClaim:
    def _run(self, calls_should_not_fire=True):
        def run(argv, **kw):
            raise AssertionError("must not dispatch a wake that cannot resume the claim")
        return run

    def test_refuses_when_incarnation_mismatches(self, wake_home, monkeypatch):
        """Someone else holds the claim: a different incarnation AND a
        different sid. (A different incarnation under this body's OWN sid is
        a seize by this body, which a wake must resume -- item 27a,
        `TestWakeAfterSeize`.)"""
        _seed_supervisor_worker(wake_home, sid=OLD_SID, status="idle")
        fleet.append_outcome(NAME, {"ts": _iso(NOW), "session_id": OLD_SID, "kind": "result"})
        _seed_claim(incarnation_id="inc-SOMEONE-ELSE", session_id="someone-elses-sid")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence((True, [])))

        with pytest.raises(fleet.FleetCliError, match="claim changed"):
            fleet.cmd_send(_send_args(message="wake up"), run=self._run(),
                           which=lambda _: "claude", sleep=lambda s: None)

        rec = fleet.load_registry()["workers"][NAME]
        assert rec["status"] == "idle"                  # pre-claim rolled back
        assert (fleet.mailbox_dir() / f"{OLD_SID}.md").read_text(encoding="utf-8").strip() \
            == "wake up"                                 # mailbox restored, not lost

    def test_tolerates_a_claim_session_id_still_naming_an_earlier_retired_sid(
            self, wake_home, monkeypatch):
        """A second wake can legitimately fire before the first woken body's
        own `sup-boot` call restamps the claim -- the claim's session_id then
        still names an EARLIER retired sid, not `old_sid`. The wake_nonce
        (checked by sup-boot itself), not sid equality, is the real
        continuity proof, so this must NOT refuse."""
        _seed_supervisor_worker(wake_home, sid=OLD_SID, status="idle")
        fleet.append_outcome(NAME, {"ts": _iso(NOW), "session_id": OLD_SID, "kind": "result"})
        _seed_claim(session_id="some-earlier-retired-sid")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []), (True, []),
            (True, [_make_roster_entry(NEW_SID, status="idle", state="working")]),
        ))

        rc = fleet.cmd_send(_send_args(message="wake up"), run=_fake_dispatch_run(),
                           which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"][NAME]
        assert rec["session_id"] == NEW_SID

    def test_refuses_when_claim_released(self, wake_home, monkeypatch):
        _seed_supervisor_worker(wake_home, sid=OLD_SID, status="idle")
        fleet.append_outcome(NAME, {"ts": _iso(NOW), "session_id": OLD_SID, "kind": "result"})
        _seed_claim(extra={"state": "released"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence((True, [])))

        with pytest.raises(fleet.FleetCliError, match="claim changed"):
            fleet.cmd_send(_send_args(message="wake up"), run=self._run(),
                           which=lambda _: "claude", sleep=lambda s: None)


class TestWakeAfterSeize:
    """Queue item 27a (MEASURED 2026-09-18): a seize keeps the body's sid but
    mints a new incarnation id, and never renames the roster row. The wake
    path used to take the incarnation from the ROW NAME, so after any seize
    every wake to that body refused with `claim changed since the wake
    decision` for the rest of the generation, while mailbox delivery to the
    same body -- mid-turn -- kept working. The live claim is the authority
    when its holder record is this very body."""

    SEIZED = "inc-seized-by-this-body"

    def test_wake_resumes_a_body_that_seized_under_a_new_incarnation(
            self, wake_home, monkeypatch):
        _seed_supervisor_worker(wake_home, sid=OLD_SID, status="idle")
        fleet.append_outcome(NAME, {"ts": _iso(NOW), "session_id": OLD_SID, "kind": "result"})
        _seed_claim(incarnation_id=self.SEIZED, session_id=OLD_SID,
                    extra={"claimed_via": "seize"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []), (True, []),
            (True, [_make_roster_entry(NEW_SID, status="idle", state="working")]),
        ))

        rc = fleet.cmd_send(_send_args(message="wake up"), run=_fake_dispatch_run(),
                            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0

        task = fleet.task_file_path(NAME).read_text(encoding="utf-8")
        assert self.SEIZED in task                  # the claim's incarnation, not the row's
        assert "incarnation inc-wtest," not in task

        wake_nonce = re.search(r"--nonce (\S+)", task).group(1)

        def boot_roster_run(argv, **kw):
            entries = [_make_roster_entry(NEW_SID, status="idle", state="working")]
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")

        boot_rc = fleet.cmd_sup_boot(
            SimpleNamespace(sid=NEW_SID, handoff_inc=None, nonce=wake_nonce),
            which=lambda _: "C:/fake/claude.cmd", run=boot_roster_run)
        assert boot_rc == 0
        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == self.SEIZED   # resumed, not a new generation
        assert claim["session_id"] == NEW_SID

    def test_a_different_body_holding_the_claim_still_refuses(self, wake_home, monkeypatch):
        """The guard's real job survives: a claim held by ANOTHER sid under
        another incarnation is a body this wake could never resume."""
        _seed_supervisor_worker(wake_home, sid=OLD_SID, status="idle")
        fleet.append_outcome(NAME, {"ts": _iso(NOW), "session_id": OLD_SID, "kind": "result"})
        _seed_claim(incarnation_id=self.SEIZED, session_id="another-body-entirely",
                    extra={"claimed_via": "seize"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence((True, [])))

        def run(argv, **kw):
            raise AssertionError("must not dispatch a wake that cannot resume the claim")

        with pytest.raises(fleet.FleetCliError, match="claim changed"):
            fleet.cmd_send(_send_args(message="wake up"), run=run,
                           which=lambda _: "claude", sleep=lambda s: None)
        rec = fleet.load_registry()["workers"][NAME]
        assert rec["status"] == "idle"
