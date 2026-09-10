"""Lifecycle reaping: young corpses retire, active work and mail survive.

Every home and daemon response is synthetic; these tests never call a daemon.
"""
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import fleet


SID = "aaaa1111-1111-2222-3333-444455556666"
RETIRED = "bbbb2222-1111-2222-3333-444455556666"
CURRENT = "cccc3333-1111-2222-3333-444455556666"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MCX_WORKER", "1")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for directory in ("state", "logs", "mailbox", "supervisor", "knowledge"):
        (tmp_path / directory).mkdir()
    (tmp_path / "state/worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "supervisor/GOALS.md").write_text("# Test goals\n", encoding="utf-8")
    fleet.save_registry({"workers": {}})
    return tmp_path


def seed(name="finished", sid=SID, **fields):
    record = fleet.new_worker_record(sid, str(fleet.FLEET_HOME), "test", "accept",
                                     dispatch_kind="bg")
    record.update(status="idle", last_activity=fleet.now_iso())
    record.update(fields)
    data = fleet.load_registry()
    data["workers"][name] = record
    fleet.save_registry(data)
    return record


def entry(sid=SID, **fields):
    result = {"id": sid[:8], "sessionId": sid, "name": "fleet|test|task",
              "kind": "background", "state": "done"}
    result.update(fields)
    return result


def runner(roster, calls):
    """A mutable fake roster makes rm effects observable across sweep tiers."""
    roster = list(roster)

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[1] in ("agents", "rm"), argv
        if argv[1] == "agents":
            return SimpleNamespace(returncode=0, stdout=json.dumps(roster), stderr="")
        roster[:] = [row for row in roster if row["id"] != argv[2]]
        return SimpleNamespace(returncode=0, stdout="removed", stderr="")
    return run


def eligible(record, roster, name="finished", reap=True):
    return fleet._archive_eligible(name, record, roster, datetime.now(timezone.utc),
                                   reap=reap)[0]


def claim(sid=CURRENT, **fields):
    nonce = "test-generation"
    value = {"incarnation_id": "inc-current", "session_id": sid,
             "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
             "claimed_via": "fresh", "nonce_hash": fleet.nonce_digest(nonce),
             "nonce_seq": 1, "lineage_id": "test-lineage"}
    value.update(fields)
    fleet.write_incarnation(value)
    return nonce


@pytest.mark.parametrize("status", ["idle", "working", "dead-suspected"])
def test_explicit_daemon_dead_ignores_age_and_stale_registry_status(home, status):
    record = seed(status=status, last_activity="unparseable")
    assert eligible(record, [entry()])
    assert not eligible(record, [], reap=True), "missing roster is not confirmed dead"


@pytest.mark.parametrize("lane_state", ["landed", "abandoned"])
@pytest.mark.parametrize("evidence", ["field", "outcome"])
def test_completed_lane_idle_is_reapable_before_ttl(home, lane_state, evidence):
    record = seed(**({"lane_state": lane_state} if evidence == "field" else {}))
    if evidence == "outcome":
        fleet.append_outcome("finished", {"session_id": SID, "kind": lane_state,
                                           "ts": fleet.now_iso()})
    assert eligible(record, [entry(status="idle")])


def test_result_is_not_a_landed_lane_and_manual_archive_keeps_ttl(home):
    record = seed()
    fleet.append_outcome("finished", {"session_id": SID, "kind": "result",
                                       "ts": fleet.now_iso()})
    assert not eligible(record, [entry(status="idle")])
    assert not eligible(record, [entry()], reap=False)
    assert eligible(record, [entry()])


def test_newer_result_overrides_old_landed_outcome(home):
    record = seed()
    for kind, ts in [("landed", "2026-01-01T00:00:00Z"),
                     ("result", "2026-01-01T00:01:00Z")]:
        fleet.append_outcome("finished", {"session_id": SID, "kind": kind, "ts": ts})
    assert not eligible(record, [entry(status="idle")])


@pytest.mark.parametrize("protected_sid", [SID, RETIRED])
@pytest.mark.parametrize("protection", ["pid", "busy", "mail", "claimed"])
def test_current_and_retired_session_safety_vetoes(home, protected_sid, protection):
    record = seed(lane_state="landed", retired_sids=[RETIRED])
    roster = [entry(), entry(RETIRED)]
    if protection in ("pid", "busy"):
        row = next(row for row in roster if row["sessionId"] == protected_sid)
        row.update({"pid": 4242} if protection == "pid" else {"status": "busy"})
    else:
        suffix = ".md.claimed.4242" if protection == "claimed" else ".md"
        (home / "mailbox" / f"{protected_sid}{suffix}").write_text("unread work", encoding="utf-8")
    assert not eligible(record, roster)


def test_predecessor_supervisor_reaps_but_current_claim_is_protected(home):
    claim()
    old = seed("sup|inc-old|successor")
    current = seed("sup|inc-current|successor", CURRENT)
    roster = [entry(status="idle"), entry(CURRENT)]
    assert eligible(old, roster, "sup|inc-old|successor")
    assert not eligible(current, roster, "sup|inc-current|successor")


def test_reap_uses_autoclean_archive_writer_and_counts_once(home):
    seed(lane_state="landed")
    calls = []
    run = runner([entry(status="idle")], calls)
    count, error = fleet._supervisor_reap(run=run, which=lambda _: "claude")
    assert count == 1 and not error
    assert fleet.load_registry()["workers"]["finished"]["archived_at"]
    assert (home / "logs/archive/finished").is_dir()
    events = [json.loads(line) for line in fleet.events_path().read_text().splitlines()]
    assert any(event["kind"] == "autoclean_run" for event in events)
    assert fleet._supervisor_reap(run=run, which=lambda _: "claude")[0] == 0


@pytest.mark.parametrize("protection", ["mail", "claimed", "holder", "pid"])
def test_resuming_partial_archive_cannot_bypass_reap_safety(home, protection):
    seed(archived_at=fleet.now_iso())
    # An evidence file left behind is what selects archive's resume path.
    task = fleet.task_file_path("finished")
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text("retained evidence", encoding="utf-8")
    roster = [entry()]
    mail = None
    if protection in ("mail", "claimed"):
        suffix = ".md" if protection == "mail" else ".md.claimed.4242"
        mail = home / "mailbox" / f"{SID}{suffix}"
        mail.write_text("must be delivered", encoding="utf-8")
    elif protection == "holder":
        claim(sid=SID)
    else:
        roster[0]["pid"] = 4242
    calls = []
    fleet._supervisor_reap(run=runner(roster, calls), which=lambda _: "claude")
    assert not any(argv[1] == "rm" for argv in calls)
    assert task.read_text() == "retained evidence"
    if mail:
        assert mail.read_text() == "must be delivered"


def test_boot_reaps_after_bundle_assembly_and_prints_nonce_once(home, monkeypatch, capsys):
    seed(lane_state="landed")
    calls = []
    render = fleet._render_boot_bundle
    seen = []

    def render_before_reap(*args, **kwargs):
        seen.append(fleet.load_registry()["workers"]["finished"]["archived_at"])
        return render(*args, **kwargs)

    monkeypatch.setattr(fleet, "_render_boot_bundle", render_before_reap)
    rc = fleet.cmd_sup_boot(SimpleNamespace(sid=CURRENT),
                            run=runner([entry(status="idle")], calls),
                            which=lambda _: "claude")
    output = capsys.readouterr().out
    assert rc == 0 and seen == [None]
    assert fleet.load_registry()["workers"]["finished"]["archived_at"]
    assert "reaped: 1 rows" in output
    assert "1.5 GB" in output and "3 live worker sessions" in output
    assert "Claude" in output and "Codex" in output
    nonces = re.findall(r"^NONCE: (\S+)$", output, re.MULTILINE)
    assert len(nonces) == 1
    assert fleet.nonce_digest(nonces[0]) == fleet.read_incarnation()["nonce_hash"]
    assert nonces[0] not in fleet.incarnation_path().read_text()


@pytest.mark.parametrize("mode", ["refused", "frozen", "pending"])
def test_unclaimed_boot_never_reaps(home, mode):
    claim(handoff_pending=[{"successor_inc": "inc-next"}])
    seed(lane_state="landed")
    calls = []
    args = SimpleNamespace(sid=RETIRED)
    if mode == "pending":
        args.handoff_inc = "inc-next"
        args.handoff_token = "test-token"
    rc = fleet.cmd_sup_boot(
        args, run=runner([entry(), entry(CURRENT, status="busy", pid=4242,
                                        state="done" if mode == "frozen" else "working")], calls),
        which=lambda _: "claude")
    assert rc == {"pending": 0, "refused": 2, "frozen": 3}[mode]
    assert fleet.load_registry()["workers"]["finished"]["archived_at"] is None
    assert not any(argv[1] == "rm" for argv in calls)


@pytest.mark.parametrize("transition", ["release", "handoff"])
def test_exit_transitions_run_reap_after_claim_change(home, transition):
    nonce = claim(handoff_token_hash=fleet.nonce_digest("token"))
    seed(lane_state="landed")
    calls = []
    run = runner([entry()], calls)
    observed = []

    def after_transition_run(argv, **kwargs):
        observed.append(fleet.read_incarnation())
        return run(argv, **kwargs)

    if transition == "release":
        rc = fleet.cmd_sup_release(SimpleNamespace(sid=CURRENT, nonce=nonce),
                                    run=after_transition_run, which=lambda _: "claude")
        assert all(value.get("state") == "released" for value in observed)
    else:
        fleet.write_handshake("inc-next", RETIRED,
                              handoff_token_hash=fleet.nonce_digest("token"),
                              nonce_hash=fleet.nonce_digest("successor-nonce"))
        rc = fleet.cmd_sup_handoff_complete(
            SimpleNamespace(sid=CURRENT, nonce=nonce, expect_inc="inc-next"),
            run=after_transition_run, which=lambda _: "claude")
        assert all(value["incarnation_id"] == "inc-next" for value in observed)
    assert rc == 0 and observed
    assert fleet.load_registry()["workers"]["finished"]["archived_at"]
    assert any(argv[1] == "rm" for argv in calls)


def test_reap_failure_keeps_successful_boot_nonce_deliverable(home, capsys):
    seed(lane_state="landed")
    calls = []
    normal_run = runner([entry()], calls)
    roster_reads = 0

    def failing_after_boot_roster(argv, **kwargs):
        nonlocal roster_reads
        if argv[1] == "agents":
            roster_reads += 1
            if roster_reads > 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="daemon unavailable")
        return normal_run(argv, **kwargs)

    assert fleet.cmd_sup_boot(SimpleNamespace(sid=CURRENT),
                               run=failing_after_boot_roster, which=lambda _: "claude") == 0
    captured = capsys.readouterr()
    assert len(re.findall(r"^NONCE: ", captured.out, re.MULTILINE)) == 1
    assert "reaped: 0 rows" in captured.out
    assert fleet.load_registry()["workers"]["finished"]["archived_at"] is None
    assert "reap" in (captured.out + captured.err).lower()


def test_partial_archive_of_current_incarnation_with_stale_sid_is_protected(home):
    name = 'sup|inc-current|successor'
    seed(name, archived_at=fleet.now_iso())
    claim(sid=CURRENT)
    task = fleet.task_file_path(name)
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text('current incarnation evidence', encoding='utf-8')
    calls = []
    fleet._supervisor_reap(run=runner([entry()], calls), which=lambda _: 'claude')
    assert task.exists()
    assert not any(argv[1] == 'rm' for argv in calls)


@pytest.mark.parametrize('protection', ['pid', 'mail', 'claimed'])
def test_partial_archive_husk_cannot_bypass_retired_sid_protection(home, protection):
    seed(archived_at=fleet.now_iso(), retired_sids=[RETIRED])
    task = fleet.task_file_path('finished')
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text('evidence', encoding='utf-8')
    roster = [entry(), entry(RETIRED)]
    if protection == 'pid':
        roster[1]['pid'] = 4242
    else:
        suffix = '.md' if protection == 'mail' else '.md.claimed.4242'
        (home / 'mailbox' / f'{RETIRED}{suffix}').write_text('unread', encoding='utf-8')
    calls = []
    fleet._supervisor_reap(run=runner(roster, calls), which=lambda _: 'claude')
    assert task.exists()
    assert not any(argv[1] == 'rm' for argv in calls)


@pytest.mark.parametrize('mail_sid', [SID, RETIRED])
def test_mail_arriving_during_archive_moves_stays_in_inbox_and_prevents_rm(home, monkeypatch,
                                                                        mail_sid):
    seed(lane_state='landed', retired_sids=[RETIRED])
    task = fleet.task_file_path('finished')
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text('evidence', encoding='utf-8')
    inbox = home / 'mailbox' / f'{mail_sid}.md'
    move = fleet._archive_move

    def delivering_move(src, dest, name):
        if src == task:
            inbox.write_text('concurrent unread work', encoding='utf-8')
        return move(src, dest, name)

    monkeypatch.setattr(fleet, '_archive_move', delivering_move)
    calls = []
    fleet._supervisor_reap(run=runner([entry(status='idle')], calls), which=lambda _: 'claude')
    assert inbox.read_text() == 'concurrent unread work'
    assert not any(argv[1] == 'rm' for argv in calls)


@pytest.mark.parametrize('transition', ['release', 'handoff'])
@pytest.mark.parametrize('forked', [False, True])
@pytest.mark.parametrize('ambiguous', [False, True])
def test_exit_reap_spares_caller_union_and_ambiguous_twins(home, transition, forked,
                                                         ambiguous):
    old_name = 'sup|inc-current|boot'
    old_sid = SID if forked else CURRENT
    before = seed(old_name, old_sid, retired_sids=[CURRENT] if forked else [])
    twin = seed('twin', CURRENT) if ambiguous else None
    other_sid = 'dddd4444-1111-2222-3333-444455556666'
    seed('other-finished', other_sid, lane_state='landed')
    task = fleet.task_file_path(old_name)
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text('caller evidence', encoding='utf-8')
    nonce = claim(handoff_token_hash=fleet.nonce_digest('token'))
    calls = []
    run = runner([entry(old_sid), entry(CURRENT), entry(other_sid)], calls)
    args = SimpleNamespace(sid=CURRENT, nonce=nonce, expect_inc='inc-next')
    if transition == 'release':
        assert fleet.cmd_sup_release(args, run=run, which=lambda _: 'claude') == 0
    else:
        fleet.write_handshake('inc-next', RETIRED,
                              handoff_token_hash=fleet.nonce_digest('token'),
                              nonce_hash=fleet.nonce_digest('next-generation'))
        assert fleet.cmd_sup_handoff_complete(args, run=run, which=lambda _: 'claude') == 0
    workers = fleet.load_registry()['workers']
    assert workers[old_name]['archived_at'] is None
    if ambiguous:
        assert workers[old_name] == before
        assert workers['twin'] == twin
    assert task.read_text() == 'caller evidence'
    assert workers['other-finished']['archived_at']
    removed = {argv[2] for argv in calls if argv[1] == 'rm'}
    assert old_sid[:8] not in removed and CURRENT[:8] not in removed
    assert other_sid[:8] in removed
    if not ambiguous:
        # Caller protection belongs to this pass, not to the released claim:
        # the next body can reap its now-dead predecessor without a TTL wait.
        count, error = fleet._supervisor_reap(run=run, which=lambda _: 'claude',
                                             caller_sid=RETIRED)
        assert count == 1 and error is None
        assert fleet.load_registry()['workers'][old_name]['archived_at']


@pytest.mark.parametrize('archived', [False, True])
@pytest.mark.parametrize('twin_status', ['idle', 'dead'])
def test_reap_ambiguity_veto_covers_archive_resumes_and_husks(home, archived, twin_status):
    # Shared retired SID makes ownership overlap even with different current
    # SIDs, or when the ordinary resolver prefers one live row over a husk.
    stamp = fleet.now_iso() if archived else None
    first = seed('first', SID, retired_sids=[CURRENT], archived_at=stamp)
    second = seed('second', RETIRED, retired_sids=[CURRENT],
                  status=twin_status, archived_at=stamp)
    task = fleet.task_file_path('first')
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text('ambiguous evidence', encoding='utf-8')
    calls = []
    fleet._supervisor_reap(run=runner([entry(), entry(RETIRED), entry(CURRENT)], calls),
                           which=lambda _: 'claude')
    assert fleet.load_registry()['workers'] == {'first': first, 'second': second}
    assert task.read_text() == 'ambiguous evidence'
    assert not any(argv[1] == 'rm' for argv in calls)
