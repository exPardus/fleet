"""sup-spawn carries --setting-sources through to the dispatched body.

On a host where ~/.claude/settings.json registers foreign Stop hooks (the
kz-work ccgram bridge), a supervisor body dispatched without
--setting-sources runs those hooks with an environment inherited from the
daemon's first dispatch and gets attributed to the wrong tmux window.
`spawn` already has the passthrough; this pins the same flag on `sup-spawn`.
"""
from types import SimpleNamespace

import pytest

import fleet
from test_sup_spawn import (  # noqa: F401  (fixtures re-exported)
    _fake_run_factory,
    _roster_with,
    _the_one_worker,
    native_home,
)
from test_sup_tombstone import (
    _fake_run_factory as _tombstone_run_factory,
    _respawn_happy,
)


def _args(setting_sources=None):
    return SimpleNamespace(task="boot and report", model=None,
                           permission_mode=None, nonce=None,
                           setting_sources=setting_sources)


def _spawn(native_home, monkeypatch, args, calls):
    # Matches test_sup_spawn.py's `_happy_spawn`: the default stdout
    # ("backgrounded * aaaabbbb * sup\n") parses to short id "aaaabbbb",
    # which _roster_with's default SID joins on the post-dispatch poll. A
    # stdout that fails to parse a short id never reaches dispatch_bg's
    # setting_sources handling at all -- it raises before argv is built,
    # which would test the fixture instead of the feature.
    monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
    run = _fake_run_factory(calls=calls)
    return fleet.cmd_sup_spawn(args, run=run, which=lambda _: "/usr/bin/claude",
                               sleep=lambda *_: None, clock=lambda: 0.0)


def test_the_flag_reaches_the_argv_after_settings(native_home, monkeypatch):
    calls = []
    assert _spawn(native_home, monkeypatch, _args("project,local"), calls) == 0
    argv = calls[0][0]
    i = argv.index("--setting-sources")
    assert argv[i + 1] == "project,local"
    assert i > argv.index("--settings")


def test_the_flag_is_persisted_on_the_supervisor_record(native_home, monkeypatch):
    calls = []
    assert _spawn(native_home, monkeypatch, _args("project,local"), calls) == 0
    _, rec = _the_one_worker()
    assert rec["setting_sources"] == "project,local"


def test_without_the_flag_nothing_changes(native_home, monkeypatch):
    calls = []
    assert _spawn(native_home, monkeypatch, _args(None), calls) == 0
    assert "--setting-sources" not in calls[0][0]
    _, rec = _the_one_worker()
    assert rec.get("setting_sources") is None


def test_the_parser_accepts_the_flag():
    parser = fleet.build_parser()
    ns = parser.parse_args(["sup-spawn", "--task", "x",
                            "--setting-sources", "project"])
    assert ns.setting_sources == "project"


# --- I4: the flag survives the bodies that follow the first one -------------
#
# `sup-spawn` carrying the flag (above) is one body's worth of remedy. The two
# paths that mint the NEXT supervisor body -- `respawn supervisor` (three-tier
# §10.4, which re-dispatches through `_dispatch_supervisor_body`) and
# `sup-handoff-begin` (SPEC §6.1's sanctioned second argv builder) -- have to
# carry it too, or the ccgram hooks come back at the first ceiling. The
# handoff half lives beside the other handoff tests, in
# tests/test_supervisor.py::TestHandoff.

def _respawn_dispatch_argv(calls):
    return next(argv for argv, _ in calls if "--bg" in argv)


def test_respawn_supervisor_carries_the_old_bodys_setting_sources(
        native_home, monkeypatch):
    calls = []
    rc = _respawn_happy(native_home, monkeypatch,
                        run=_tombstone_run_factory(calls=calls),
                        holder={"setting_sources": "project,local"})
    assert rc == 0
    argv = _respawn_dispatch_argv(calls)
    i = argv.index("--setting-sources")
    assert argv[i + 1] == "project,local"
    assert i > argv.index("--settings")
    # and persisted on the fresh gen-0 record, so the body after THIS one
    # reads it back the same way
    workers = fleet.load_registry()["workers"]
    fresh = [r for n, r in workers.items() if n != "sup|inc-1|boot"]
    assert len(fresh) == 1, workers
    assert fresh[0]["setting_sources"] == "project,local"


def test_respawn_supervisor_without_the_flag_adds_nothing(native_home, monkeypatch):
    calls = []
    rc = _respawn_happy(native_home, monkeypatch,
                        run=_tombstone_run_factory(calls=calls))
    assert rc == 0
    assert "--setting-sources" not in _respawn_dispatch_argv(calls)
