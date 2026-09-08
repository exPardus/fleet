"""The keeper's rules are pure: one observation in, zero or more pages out.

Each rule is tested with a known-firing and a known-silent observation so a
rule that never fires (or always fires) cannot pass.
"""
import fleet_keeper as k

NOW = 1_800_000_000.0


def _obs(**over):
    base = {
        "goals_active": True,
        "claim_state": "held",
        "heartbeat_age_seconds": 120.0,
        "pending_decision": None,
        "sup_sessions": ["sup|launch-1|boot"],
        "agents_ok": True,
        "registry_ok": True,
        "registry_reason": None,
        "workers": [],
        "unpushed": 0,
        "oldest_unpushed_ts": None,
        "hook_error_lines": 0,
        "prev_hook_error_lines": 0,
    }
    base.update(over)
    return base


def _rules(pages):
    return sorted(p.rule for p in pages)


def test_a_healthy_fleet_pages_nothing():
    assert k.evaluate(_obs(), NOW) == []


def test_released_claim_with_goals_active_pages_supervisor_dead():
    pages = k.evaluate(_obs(claim_state="released", sup_sessions=[]), NOW)
    assert _rules(pages) == ["supervisor-dead"]
    assert pages[0].text.startswith("KEEPER: supervisor dead")
    assert "await operator" in pages[0].text


def test_absent_claim_with_goals_active_pages_supervisor_dead():
    pages = k.evaluate(_obs(claim_state="none", sup_sessions=[],
                            heartbeat_age_seconds=None), NOW)
    assert _rules(pages) == ["supervisor-dead"]


def test_stale_heartbeat_with_no_sup_session_pages_supervisor_dead():
    pages = k.evaluate(_obs(heartbeat_age_seconds=k.HEARTBEAT_STALE_SECONDS + 1,
                            sup_sessions=[]), NOW)
    assert _rules(pages) == ["supervisor-dead"]


def test_stale_heartbeat_with_a_live_sup_session_is_silent():
    # A body mid-turn can miss a beat; a live roster entry means not dead.
    pages = k.evaluate(_obs(heartbeat_age_seconds=k.HEARTBEAT_STALE_SECONDS + 1,
                            sup_sessions=["sup|launch-1|boot"]), NOW)
    assert pages == []


def test_goals_inactive_never_pages_supervisor_dead():
    pages = k.evaluate(_obs(goals_active=False, claim_state="none",
                            sup_sessions=[]), NOW)
    assert "supervisor-dead" not in _rules(pages)


def test_pending_decision_pages_supervisor_frozen():
    pages = k.evaluate(_obs(pending_decision="ship M-F?"), NOW)
    assert _rules(pages) == ["supervisor-frozen"]
    assert "ship M-F?" in pages[0].text


def test_worker_anomalies_page_once_with_all_names():
    workers = [
        {"name": "a", "status": "dead-suspected", "mail": 0, "limit_kind": None},
        {"name": "b", "status": "limited", "mail": 0, "limit_kind": "usage"},
        {"name": "c", "status": "idle", "mail": 2, "limit_kind": None},
        {"name": "d", "status": "working", "mail": 0, "limit_kind": None},
    ]
    pages = k.evaluate(_obs(workers=workers), NOW)
    assert _rules(pages) == ["worker-anomaly"]
    text = pages[0].text
    assert "3 worker anomalies" in text
    for name in ("a", "b", "c"):
        assert name in text
    assert "d(" not in text


def test_unpushed_pages_only_after_the_window():
    young = _obs(unpushed=3, oldest_unpushed_ts=NOW - 3600)
    old = _obs(unpushed=3, oldest_unpushed_ts=NOW - k.UNPUSHED_PAGE_SECONDS - 1)
    assert k.evaluate(young, NOW) == []
    pages = k.evaluate(old, NOW)
    assert _rules(pages) == ["unpushed"]
    assert "3 commits unpushed" in pages[0].text


def test_agents_failure_pages_login_expired():
    pages = k.evaluate(_obs(agents_ok=False, sup_sessions=[]), NOW)
    assert "login-expired" in _rules(pages)
    # and it must NOT also claim the supervisor is dead on evidence it lacks
    assert "supervisor-dead" not in _rules(pages)


def test_hook_errors_growth_pages_with_the_delta():
    pages = k.evaluate(_obs(hook_error_lines=12, prev_hook_error_lines=10), NOW)
    assert _rules(pages) == ["hook-errors"]
    assert "grew by 2 lines" in pages[0].text


def test_unreadable_registry_pages_and_repairs_nothing():
    pages = k.evaluate(_obs(registry_ok=False, registry_reason="quarantined"), NOW)
    assert _rules(pages) == ["registry-unreadable"]
    assert "quarantined" in pages[0].text


def test_fingerprints_change_when_the_situation_changes():
    a = k.evaluate(_obs(unpushed=3, oldest_unpushed_ts=NOW - 8 * 3600), NOW)[0]
    b = k.evaluate(_obs(unpushed=4, oldest_unpushed_ts=NOW - 8 * 3600), NOW)[0]
    assert a.rule == b.rule and a.fingerprint != b.fingerprint


def test_every_page_is_one_line():
    obs = _obs(claim_state="released", sup_sessions=[], pending_decision="q?",
               workers=[{"name": "a", "status": "dead-suspected", "mail": 0,
                         "limit_kind": None}],
               unpushed=1, oldest_unpushed_ts=NOW - 9 * 3600,
               hook_error_lines=1, prev_hook_error_lines=0)
    for p in k.evaluate(obs, NOW):
        assert "\n" not in p.text and p.text.startswith("KEEPER: ")
