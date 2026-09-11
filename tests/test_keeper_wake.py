"""G-K8 C: a real guard decision drives a tick; all external actions are fakes."""
import io
import json
import subprocess
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest

import fleet
import fleet_keeper as k

SID = 'sid-current'
BODY = 'sup|inc-wake|boot'
NOW = 1_800_000_000.0


@pytest.fixture
def tick(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, 'FLEET_HOME', tmp_path)
    monkeypatch.setattr(fleet, '_reap_current_supervisor_forks', lambda **_: [])
    for directory in ('state', 'supervisor', 'mailbox', 'logs'):
        (tmp_path / directory).mkdir()
    fleet.save_registry({'workers': {BODY: fleet.new_worker_record(
        SID, str(tmp_path), 'standing', 'bypass', dispatch_kind='bg')}})
    fleet.write_incarnation({'incarnation_id': 'inc-wake', 'session_id': SID,
                             'claimed_via': 'handoff', 'heartbeat_at': '2026-01-01T00:00:00Z'})
    monkeypatch.setattr(fleet, 'cmd_sup_spawn', lambda _: pytest.fail('keeper spawned'))
    monkeypatch.setattr(k, 'collect', lambda *a, **kw: {
        'goals_active': True, 'claim_state': 'held', 'hook_error_lines': 0})
    monkeypatch.setattr(k, '_registered_pane_details', lambda *a, **kw: ('%42', 'ok'))
    monkeypatch.setattr(k, 'report_interface_candidates', lambda *a, **kw: None)
    pages, sends, commands = [], [], []
    monkeypatch.setattr(k, 'page', lambda run, target, text, **kw: pages.append(text) or True)
    monkeypatch.setattr(fleet, 'cmd_send', lambda args: sends.append(args) or 0)

    def invoke(*, age=4000, pid=42, status='idle', horizon=None, now=NOW,
               dry=False, error=None, page_ok=True):
        snap = {'ok': True, 'workers': [], 'supervisor': {
            'goals_active': True, 'state': 'held', 'heartbeat_age_seconds': age}}
        row = {'sessionId': SID, 'name': BODY, 'state': 'working',
               'status': status, 'pid': pid, 'limit_reset_at': horizon}
        def run(argv, **kwargs):
            assert 'sup-guard' in argv
            assert '--fleet-home' in argv and str(tmp_path) in argv
            assert 'CLAUDE_CODE_SESSION_ID' not in kwargs['env']
            commands.append(argv)
            if error:
                raise error
            output = io.StringIO()
            with redirect_stdout(output):
                rc = fleet.cmd_sup_guard(SimpleNamespace(do='--do' in argv, json=True),
                    snapshot_fn=lambda: snap, roster_fn=lambda: (True, [row]))
            return subprocess.CompletedProcess(argv, rc, output.getvalue(), '')
        monkeypatch.setattr(k, 'page', lambda run, target, text, **kw:
                            pages.append(text) or page_ok)
        return k.main(['--once', '--fleet-home', str(tmp_path)] +
                      (['--dry-run'] if dry else []), run=run,
                      now_fn=lambda: now, out=io.StringIO())
    return invoke, pages, sends, commands, tmp_path


def test_stale_idle_pid_sends_once_without_page(tick):
    invoke, pages, sends, commands, _ = tick
    assert invoke() == 0
    assert len(sends) == 1
    assert sends[0].message == '@supervisor/briefs/wake.md'
    assert not pages
    assert len(commands) == 1 and '--do' in commands[0]


def test_stale_idle_no_pid_pages_never_spawns(tick):
    invoke, pages, sends, _, _ = tick
    invoke(pid=None)
    assert not sends and len(pages) == 1
    assert 'sup-spawn' in pages[0]


@pytest.mark.parametrize('status', ['idle', 'busy'])
def test_fresh_live_body_does_nothing(tick, status):
    invoke, pages, sends, _, _ = tick
    invoke(age=10, status=status)
    assert not sends and not pages


def test_fresh_pidless_body_pages_without_wake_or_spawn(tick):
    invoke, pages, sends, _, _ = tick
    invoke(age=10, pid=None)
    assert not sends and len(pages) == 1
    assert 'fresh heartbeat but body is not roster-live' in pages[0]
    assert 'sup-spawn' not in pages[0]


@pytest.mark.parametrize('do', [False, True])
def test_keeper_accepts_ok_without_quiet_flag(tmp_path, do):
    result = k._supervisor_guard(tmp_path, lambda argv, **kw:
        subprocess.CompletedProcess(argv, 0, json.dumps({
            'verdict': 'OK', 'reason': 'fresh heartbeat with live body'}), ''), do=do)
    assert result['verdict'] == 'OK'
    assert result['quiet'] is False and result['sent'] is False
    assert k.rule_supervisor_stalled({'supervisor_guard': result}, NOW) is None


def test_limited_pages_once_even_beyond_six_hours_before_horizon(tick):
    invoke, pages, sends, _, home = tick
    for offset in (0, 900, 7 * 3600, 24 * 3600):
        invoke(status='limited', horizon='2099-01-01T00:00:00Z', now=NOW + offset)
    assert not sends
    assert len(pages) == 1 and 'supervisor limited' in pages[0]
    assert 'limited:' in json.loads((home / 'state/keeper/last-page.json').read_text())[
        'supervisor-stalled']['fingerprint']


def test_unknown_limit_horizon_pages_once_without_retry(tick):
    invoke, pages, sends, _, _ = tick
    invoke(status='limited')
    invoke(status='limited', now=NOW + 8 * 3600)
    assert len(pages) == 1 and not sends


def test_failed_limited_page_is_retried(tick):
    invoke, pages, sends, _, _ = tick
    invoke(status='limited', page_ok=False)
    invoke(status='limited', now=NOW + 900)
    assert len(pages) == 2 and not sends


def test_busy_stale_body_pages(tick):
    invoke, pages, sends, _, _ = tick
    invoke(status='busy')
    assert not sends and len(pages) == 1 and 'roster says busy' in pages[0]


def test_guard_transport_failure_stays_loud(tick):
    invoke, pages, sends, _, _ = tick
    invoke(error=subprocess.TimeoutExpired('guard', 180))
    assert not sends and len(pages) == 1 and 'guard unavailable' in pages[0]


def test_send_refusal_stays_loud(tick, monkeypatch):
    invoke, pages, sends, _, _ = tick
    monkeypatch.setattr(fleet, 'cmd_send', lambda _: 1)
    invoke()
    assert not sends and len(pages) == 1 and 'send failed' in pages[0]


def test_dry_run_observes_without_send_page_or_state(tick):
    invoke, pages, sends, commands, home = tick
    invoke(dry=True)
    assert not pages and not sends and '--do' not in commands[0]
    assert not (home / 'state/keeper/last-page.json').exists()


@pytest.mark.parametrize('flag', ['--wake-socket', '--wake-key'])
def test_socket_flags_removed(flag):
    with pytest.raises(SystemExit) as exc:
        k._parser().parse_args(['--once', flag, '/unused'])
    assert exc.value.code == 2


@pytest.mark.parametrize('output', ['{}', 'null', '[]', 'not json',
                                  '{"verdict":"BOGUS"}'])
def test_malformed_guard_output_becomes_page(output, tmp_path):
    result = k._supervisor_guard(tmp_path, lambda argv, **kw:
        subprocess.CompletedProcess(argv, 0, output, ''), do=True)
    assert result['verdict'].startswith('PAGE')


def test_limited_supervisor_is_not_also_a_worker_anomaly(tick, monkeypatch):
    invoke, pages, sends, _, _ = tick
    monkeypatch.setattr(k, 'collect', lambda *a, **kw: {
        'goals_active': True, 'claim_state': 'held', 'hook_error_lines': 0,
        'workers': [{'name': BODY, 'status': 'limited', 'mail': 0}]})
    invoke(status='limited', horizon='2099-01-01T00:00:00Z')
    invoke(status='limited', horizon='2099-01-01T00:00:00Z', now=NOW + 7 * 3600)
    assert len(pages) == 1 and not sends
    assert 'supervisor limited' in pages[0]
