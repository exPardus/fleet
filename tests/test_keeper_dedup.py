import json

import fleet_keeper as k

NOW = 1_800_000_000.0
P = k.Page("supervisor-dead", "released", "KEEPER: supervisor dead")


def test_first_page_is_sent_and_recorded():
    send, state = k.dedup([P], {}, NOW)
    assert send == [P]
    assert state == {"supervisor-dead": {"fingerprint": "released", "at": NOW}}


def test_same_fingerprint_inside_the_window_is_suppressed():
    _, state = k.dedup([P], {}, NOW)
    send, state2 = k.dedup([P], state, NOW + 900)
    assert send == []
    assert state2 == state  # untouched, so the window does not slide


def test_same_fingerprint_after_the_window_repages():
    _, state = k.dedup([P], {}, NOW)
    send, state2 = k.dedup([P], state, NOW + k.REPAGE_SECONDS + 1)
    assert send == [P]
    assert state2["supervisor-dead"]["at"] == NOW + k.REPAGE_SECONDS + 1


def test_changed_fingerprint_repages_immediately():
    _, state = k.dedup([P], {}, NOW)
    p2 = P._replace(fingerprint="none")
    send, _ = k.dedup([p2], state, NOW + 60)
    assert send == [p2]


def test_a_rule_that_stops_firing_is_forgotten():
    _, state = k.dedup([P], {}, NOW)
    send, state2 = k.dedup([], state, NOW + 60)
    assert send == [] and state2 == {}


def test_state_roundtrip_and_corrupt_file(tmp_path):
    path = tmp_path / "keeper" / "last-page.json"
    k.save_state(path, {"x": {"fingerprint": "f", "at": 1.0}})
    assert k.load_state(path) == {"x": {"fingerprint": "f", "at": 1.0}}
    path.write_text("{not json", encoding="utf-8")
    assert k.load_state(path) == {}
    assert k.load_state(tmp_path / "absent.json") == {}
