import json

import fleet_keeper as k

NOW = 1_800_000_000.0
P = k.Page("supervisor-stalled", "released", "KEEPER: supervisor stalled")


def test_first_page_is_sent_and_recorded():
    send, state = k.dedup([P], {}, NOW)
    assert send == [P]
    assert state == {"supervisor-stalled": {"fingerprint": "released", "at": NOW}}


def test_same_fingerprint_inside_the_window_is_suppressed():
    _, state = k.dedup([P], {}, NOW)
    send, state2 = k.dedup([P], state, NOW + 900)
    assert send == []
    assert state2 == state  # untouched, so the window does not slide


def test_same_fingerprint_after_the_window_repages():
    _, state = k.dedup([P], {}, NOW)
    send, state2 = k.dedup([P], state, NOW + k.REPAGE_SECONDS + 1)
    assert send == [P]
    assert state2["supervisor-stalled"]["at"] == NOW + k.REPAGE_SECONDS + 1


def test_changed_fingerprint_repages_immediately():
    _, state = k.dedup([P], {}, NOW)
    p2 = P._replace(fingerprint="none")
    send, _ = k.dedup([p2], state, NOW + 60)
    assert send == [p2]


def test_a_rule_that_stops_firing_is_forgotten():
    _, state = k.dedup([P], {}, NOW)
    send, state2 = k.dedup([], state, NOW + 60)
    assert send == [] and state2 == {}


def test_a_held_stale_supervisor_stalled_page_dedups_across_a_tick():
    """End-to-end version of the beat-free fingerprint fix (re-review minor
    1): the same held+stale situation, observed 15 minutes apart with the
    heartbeat age advanced, must not re-page -- only the fingerprint (which
    no longer carries the age) governs dedup."""
    sid = "11111111-2222-3333-4444-555555555555"

    def obs(beat):
        return {"goals_active": True, "claim_state": "held", "claim_sid": sid,
                "claim_rows": {sid: "idle"}, "claim_sids": [sid],
                "sid_union_ok": True,
                "heartbeat_age_seconds": beat,
                "supervisor_guard": {"verdict": "PAGE roster says busy",
                                     "reason": "roster says busy", "body_name": "body"}}

    p1 = k.evaluate(obs(3601), NOW)[0]
    send1, state = k.dedup([p1], {}, NOW)
    assert "roster says busy" in p1.text
    assert send1 == [p1]

    p2 = k.evaluate(obs(4501), NOW + 900)[0]
    send2, state2 = k.dedup([p2], state, NOW + 900)
    assert send2 == []
    assert state2 == state


def test_state_roundtrip_and_corrupt_file(tmp_path):
    path = tmp_path / "keeper" / "last-page.json"
    k.save_state(path, {"x": {"fingerprint": "f", "at": 1.0}})
    assert k.load_state(path) == {"x": {"fingerprint": "f", "at": 1.0}}
    path.write_text("{not json", encoding="utf-8")
    assert k.load_state(path) == {}
    assert k.load_state(tmp_path / "absent.json") == {}
