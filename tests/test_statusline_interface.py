"""w106: the interface bar -- one compact row per home, less noise.

Operator, 2026-09-28: "get the fleet statusbar fixed up -- SHOW ALL MY HOMES,
LESS NOISE". Contract in docs/specs/terminal-surface.md §4.3 ("Interface
mode"); code in `bin/fleet_statusline.py` ("interface mode").

Isolation follows tests/test_statusline_home.py: the homes list is redirected
per test, and `TMUX_PANE` is set or deleted explicitly by every test that runs
`main()`, so a suite run inside tmux cannot flip a test into interface mode.
"""

from __future__ import annotations

import builtins
import io
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402
import fleet_statusline as sl  # noqa: E402

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return _ANSI.sub("", text)


def ago(seconds: float) -> str:
    t = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def rec(status="idle", age=10.0, sid="s"):
    return {"session_id": sid, "status": status, "cwd": "/x",
            "last_activity": ago(age), "turns": 1, "cost_usd": 0.0}


# --- fixtures ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def sandboxed_list(tmp_path, monkeypatch):
    fake = tmp_path / "fake-claude" / "fleet-homes.list"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(fleet, "homes_list_path", lambda: fake)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    return fake


@pytest.fixture
def home(tmp_path):
    """An initialized home. `goals` writes an active GOALS.md; `claim` writes
    supervisor/INCARNATION; `pane`/`session` write the interface registration
    exactly where `fleet interface-register` puts it."""
    def make(name, workers=None, goals=True, claim=None, pane=None,
             session=None):
        h = tmp_path / name
        (h / "state").mkdir(parents=True, exist_ok=True)
        (h / "state" / "fleet.json").write_text(
            json.dumps({"workers": workers or {}}), encoding="utf-8")
        if goals or claim:
            (h / "supervisor").mkdir(exist_ok=True)
        if goals:
            (h / "supervisor" / "GOALS.md").write_text("# goals\n",
                                                       encoding="utf-8")
        if claim:
            (h / "supervisor" / "INCARNATION").write_text(
                json.dumps(claim), encoding="utf-8")
        if pane:
            (h / "state" / "interface-pane").write_text(pane + "\n",
                                                        encoding="utf-8")
        if session:
            (h / "state" / "interface-session").write_text(session + "\n",
                                                           encoding="utf-8")
        return h
    return make


HELD = {"incarnation_id": "inc-1", "session_id": "sup-sid",
        "heartbeat_at": ago(60)}
RELEASED = {"incarnation_id": "inc-0", "state": "released"}


@pytest.fixture
def machine(sandboxed_list, monkeypatch):
    """Install + default = `first`; the list = every home given."""
    def go(first, *others):
        sandboxed_list.write_text(
            "".join(fleet.home_identity(h) + "\n" for h in (first, *others)),
            encoding="utf-8")
        monkeypatch.setattr(fleet, "INSTALL_ROOT", first)
        monkeypatch.setattr(fleet, "FLEET_HOME", first)
    return go


@pytest.fixture
def run_main(monkeypatch, capsys):
    def go(payload='{"session_id": "iface-sid"}', pane=None):
        if pane is not None:
            monkeypatch.setenv("TMUX_PANE", pane)
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
        rc = sl.main()
        return rc, capsys.readouterr().out.splitlines()
    return go


def plate(h):
    return f"[{h.name}:{fleet.home_tag(h)}]"


# --- the interface signal -----------------------------------------------------

class TestInterfaceSignal:
    def test_the_registered_pane_selects_the_home(self, home, machine, run_main):
        base = home("fleet", {"w1": rec("working")}, claim=RELEASED)
        pm = home("pm", {"sup|inc-1|boot": rec("idle", 720, "sup-sid"),
                         "lane": rec("working")}, claim=HELD, pane="%0")
        machine(base, pm)
        rc, rows = run_main(pane="%0")
        assert rc == 0
        assert rows == [f"{plate(base)}  sup none  work 1",
                        f"{plate(pm)}  sup idle 12m  work 1"]

    def test_the_registered_session_selects_the_home(self, home, machine,
                                                     run_main):
        base = home("fleet", goals=False)
        pm = home("pm", {"lane": rec("working")}, goals=False,
                  session="iface-sid")
        machine(base, pm)
        rc, rows = run_main()
        assert rc == 0 and rows == [f"{plate(pm)}  work 1"]

    def test_another_pane_is_not_the_interface(self, home, machine, run_main):
        """A stale registration (a pane id from an earlier tmux server) does
        not put its home on a different pane's bar."""
        base = home("fleet", {"w1": rec("working")}, goals=False)
        pm = home("pm", {"lane": rec("working")}, pane="%1")
        machine(base, pm)
        rc, rows = run_main(pane="%0")
        assert rc == 0
        assert rows == [sl.render_statusline(fleet.status_snapshot(),
                                             color=False,
                                             tag=fleet.home_tag(base))]

    @pytest.mark.parametrize("pane", ["0", "%", "%1a", "%0\n", ""])
    def test_a_malformed_pane_matches_nothing(self, home, pane):
        pm = home("pm", pane="%0")
        pop = {"homes": [str(pm)]}
        assert sl.interface_homes(pop, sid="", pane=pane) == []

    def test_a_single_home_machine_never_enters_interface_mode(
            self, home, monkeypatch, run_main):
        """§5's arming paragraph: one home is byte-identical to today, whatever
        registration files exist."""
        only = home("only", {"w": rec("working")}, goals=False, pane="%0")
        monkeypatch.setattr(fleet, "INSTALL_ROOT", only)
        monkeypatch.setattr(fleet, "FLEET_HOME", only)
        expected = sl.render_statusline(fleet.status_snapshot(), color=False)
        rc, rows = run_main(pane="%0")
        assert rc == 0 and rows == [expected] and expected == "[fleet]  work 1"


# --- the compact row ----------------------------------------------------------

class TestHomeRow:
    def _row(self, h):
        saved = fleet.FLEET_HOME
        try:
            fleet.FLEET_HOME = h
            return sl.render_home_row(fleet.status_snapshot(), h, color=False)
        finally:
            fleet.FLEET_HOME = saved

    def test_working_supervisor(self, home):
        h = home("pm", {"sup|inc-1|boot": rec("working", 5, "sup-sid")},
                 claim=HELD)
        assert self._row(h) == f"{plate(h)}  sup working"

    def test_idle_supervisor_carries_its_age(self, home):
        h = home("pm", {"sup|inc-1|boot": rec("idle", 1800, "sup-sid"),
                        "l": rec("working")}, claim=HELD)
        assert self._row(h) == f"{plate(h)}  sup idle 30m  work 1"

    def test_an_old_idle_supervisor_is_stale(self, home):
        h = home("pm", {"sup|inc-1|boot": rec("idle", 3 * 3600, "sup-sid")},
                 claim=HELD)
        assert self._row(h) == f"{plate(h)}  sup stale 3h"

    def test_a_held_claim_with_no_live_body_uses_the_heartbeat(self, home):
        claim = dict(HELD, heartbeat_at=ago(5 * 3600))
        h = home("pm", {"sup|inc-1|boot": rec("dead", 10, "sup-sid")},
                 claim=claim)
        assert self._row(h) == f"{plate(h)}  sup stale 5h"

    def test_lanes_finished_since_the_supervisors_turn_are_unread(self, home):
        h = home("pm", {
            "sup|inc-1|boot": rec("idle", 600, "sup-sid"),
            "done-after": rec("idle", 60),          # stopped after sup's turn
            "dead-after": rec("dead", 120),         # so did this one
            "done-before": rec("idle", 3600),       # sup already saw it
            "running": rec("working", 5),
        }, claim=HELD)
        assert self._row(h) == (f"{plate(h)}  sup idle 10m  work 1  "
                                f"done 2 unread")

    def test_two_live_bodies_still_alarm(self, home):
        h = home("pm", {"sup|inc-1|boot": rec("idle", 60, "a"),
                        "sup|inc-2|boot": rec("working", 60, "b")},
                 claim=HELD)
        assert self._row(h) == f"{plate(h)}  sup working  2 bodies"

    def test_a_frozen_home_is_suppressed(self, home):
        h = home("fleet", {"sup|inc-0|boot": rec("dead", 9),
                           "old": rec("idle", 9), "gone": rec("dead", 9)},
                 claim=RELEASED)
        assert self._row(h) is None

    def test_no_dead_counter_on_a_compact_row(self, home):
        h = home("pm", {"l": rec("working")} | {
            f"d{i}": rec("dead", 9999) for i in range(7)}, goals=False)
        assert self._row(h) == f"{plate(h)}  work 1"

    def test_a_registry_fault_is_never_suppressed(self, home):
        h = home("pm")
        (h / "state" / "fleet.json").write_text("not json", encoding="utf-8")
        assert self._row(h) == f"{plate(h)}  registry unreadable"

    def test_a_hostile_directory_name_cannot_forge_a_nameplate(self, tmp_path):
        h = tmp_path / "x]\x1b[2K[fleet"
        line = sl.home_nameplate(h)
        assert "\x1b" not in line and line.count("[") == 1
        assert line.count("]") == 1 and len(line) <= 1 + 12 + 1 + 4 + 1


# --- the bar ------------------------------------------------------------------

class TestBar:
    def test_all_frozen_renders_one_grey_frozen_row(self, home, machine,
                                                    run_main):
        base = home("fleet", {"w": rec("dead")}, claim=RELEASED)
        pm = home("pm", {"w": rec("idle")}, claim=RELEASED, pane="%3")
        machine(base, pm)
        rc, rows = run_main(pane="%3")
        assert rc == 0 and rows == [f"{plate(base)} frozen"]
        coloured = sl.render_frozen_row(base, color=True)
        assert coloured.startswith(sl._GREY) and coloured.count(sl._GREY) == 1

    def test_a_frozen_home_drops_out_beside_a_live_one(self, home, machine,
                                                        run_main):
        base = home("fleet", {"w": rec("dead")}, claim=RELEASED)
        pm = home("pm", {"l": rec("working")}, goals=False, pane="%3")
        machine(base, pm)
        rc, rows = run_main(pane="%3")
        assert rc == 0 and rows == [f"{plate(pm)}  work 1"]

    def test_at_most_four_rows(self, home, machine, run_main):
        homes = [home(f"h{i}", {"l": rec("working")}, goals=False, pane="%5")
                 for i in range(7)]
        machine(*homes)
        rc, rows = run_main(pane="%5")
        assert rc == 0 and len(rows) == sl.INTERFACE_MAX_ROWS
        assert rows[-1] == "+4 homes"
        assert all(len(r) <= 200 for r in rows)

    def test_the_resolved_home_is_not_listed_twice(self, home, machine,
                                                   run_main):
        base = home("fleet", {"l": rec("working")}, goals=False, pane="%2")
        other = home("other", goals=False)
        machine(base, other)
        rc, rows = run_main(pane="%2")
        assert rc == 0 and rows == [f"{plate(base)}  work 1"]

    def test_one_home_that_raises_costs_only_its_row(self, home, monkeypatch):
        a, b = home("a", {"l": rec("working")}, goals=False), home("b")
        real = fleet.status_snapshot

        def snap():
            if fleet.FLEET_HOME == b:
                raise RuntimeError("boom")
            return real()
        rows = sl.render_interface_rows([str(a), str(b)], color=False,
                                        snapshot=snap)
        assert rows == [f"{plate(a)}  work 1"]

    def test_the_global_home_is_restored(self, home, monkeypatch):
        a = home("a", goals=False)
        monkeypatch.setattr(fleet, "FLEET_HOME", Path("/sentinel"))
        sl.render_interface_rows([str(a)], color=False)
        assert fleet.FLEET_HOME == Path("/sentinel")

    def test_every_row_is_pure_ascii(self, home, machine, run_main,
                                     monkeypatch):
        monkeypatch.delenv("NO_COLOR")
        base = home("fleet", {"sup|inc-1|boot": rec("idle", 900, "sup-sid"),
                              "l": rec("working"), "d": rec("idle", 1)},
                    claim=HELD, pane="%0")
        other = home("pm", {"l": rec("working")}, pane="%0")
        machine(base, other)
        rc, rows = run_main(pane="%0")
        assert rc == 0 and len(rows) == 2
        assert all(r.isascii() for r in rows)

    def test_a_crash_anywhere_exits_zero(self, home, machine, run_main,
                                         monkeypatch):
        base = home("fleet", goals=False, pane="%0")
        other = home("pm", goals=False)
        machine(base, other)
        monkeypatch.setattr(sl, "render_interface_rows",
                            lambda *a, **k: 1 / 0)
        rc, _ = run_main(pane="%0")
        assert rc == 0


# --- the doctrine (CLAUDE.md: views never lock, probe, write, quarantine) -----

class TestDoctrine:
    def test_interface_mode_writes_nothing_and_spawns_nothing(
            self, home, machine, run_main, monkeypatch):
        base = home("fleet", {"l": rec("working")}, claim=HELD, pane="%0")
        pm = home("pm", {"l": rec("working")}, claim=HELD, pane="%0")
        (pm / "state" / "fleet.json").write_text("{bad", encoding="utf-8")
        machine(base, pm)
        real_open = builtins.open

        def guarded(file, mode="r", *a, **k):
            if isinstance(mode, str) and any(c in mode for c in "wxa+"):
                raise AssertionError(f"opened {file!r} for write")
            return real_open(file, mode, *a, **k)

        def no_spawn(*a, **k):
            raise AssertionError("spawned a subprocess")
        monkeypatch.setattr(builtins, "open", guarded)
        monkeypatch.setattr(io, "open", guarded)
        monkeypatch.setattr(subprocess, "run", no_spawn)
        monkeypatch.setattr(subprocess, "Popen", no_spawn)
        monkeypatch.setattr(fleet, "fleet_lock", no_spawn)
        rc, rows = run_main(pane="%0")
        assert rc == 0
        assert rows[-1] == f"{plate(pm)}  registry unreadable"
        # The corrupt registry was read, not quarantined.
        assert (pm / "state" / "fleet.json").read_text(encoding="utf-8") == "{bad"
