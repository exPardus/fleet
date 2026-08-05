"""three-tier §11.3 -- `fleet respawn` inside the 200k hard ceiling, BOTH ARMS.

The ceiling (`_ceiling_refuses_dispatch`) is a dispatch refusal aimed at exactly
one caller, the supervisor claim-holder, at or above `SUPERVISOR_BAND_HARD_TOKENS`. It had
three call sites -- `spawn`, `send`, `sup-spawn` -- and `respawn` was not one of
them. That was an omission, not a designed exemption: a supervisor incarnation
dispatched a fix wave at 224,321 tokens of occupancy through this path and
nothing refused it.

`respawn` is TWO verbs wearing one name, and only one of them is a dispatch:

  * `--task` SUPPLIED  -> §11.3 new-task dispatch. REFUSED over the ceiling,
    exactly as `spawn` and `send` are.
  * `--task` ABSENT    -> §11.4 recovery of an over-band worker. PERMITTED over
    the ceiling. This is the lever that FIXES an over-band body; refusing it
    would make the ceiling self-sealing -- the one state the remedy exists for
    would be the one state the remedy is refused in. `docs/specs/claim-nonce.md`
    §7.2 already rules on that shape: a guard whose refusal set contains its own
    remedy is a circular dependency.

Both arms are pinned here. The carve-out arm is the load-bearing one: it is what
stops a later body from "tidying up" the asymmetry into a uniform refusal and
sealing the ceiling shut.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def ceil_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs"):
        (tmp_path / sub).mkdir()
    # A clean env each test: no interface/worker stamp, no session leaking in.
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return tmp_path


def _held(session_id):
    return {"incarnation_id": "inc-x", "session_id": session_id, "state": "active",
            "nonce_hash": "deadbeef", "nonce_seq": 3, "heartbeat_at": fleet.now_iso()}


def _as_over_ceiling_holder(monkeypatch, occupancy=405000):
    """The one caller the ceiling is aimed at, past the hard top."""
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
    monkeypatch.setenv("FLEET_WORKER", "supervisor")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
    fleet.write_incarnation(_held("sid-holder"))
    monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
    monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: occupancy)


def _respawn_args(task=None, name="w1"):
    return SimpleNamespace(name=name, task=task, force=False, yes=True, nonce=None,
                           max_budget_usd=None, setting_sources=None,
                           token_ceiling=None)


# --------------------------------------------------------------------------
# Arm 1 -- `--task` supplied is a dispatch, and is refused.
# --------------------------------------------------------------------------
class TestRespawnWithATaskIsRefusedOverTheCeiling:
    def test_cmd_respawn_with_task_refuses(self, ceil_home, monkeypatch):
        _as_over_ceiling_holder(monkeypatch)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_respawn(_respawn_args(task="a brand new wave"))
        assert "11.3" in str(ei.value)
        assert "respawn" in str(ei.value)

    def test_cmd_respawn_native_with_task_refuses(self, ceil_home, monkeypatch):
        # The inner body carries its own call site, so a direct call (or a
        # future second route into it) is covered too, not only `cmd_respawn`.
        _as_over_ceiling_holder(monkeypatch)
        before = {"session_id": "sid-old", "cwd": str(ceil_home), "mode": "acceptEdits"}
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet._cmd_respawn_native(_respawn_args(task="a brand new wave"), before)
        assert "11.3" in str(ei.value)

    def test_the_refusal_fires_at_the_exact_ceiling_too(self, ceil_home, monkeypatch):
        _as_over_ceiling_holder(monkeypatch, occupancy=fleet.SUPERVISOR_BAND_HARD_TOKENS)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_respawn(_respawn_args(task="go"))
        assert "11.3" in str(ei.value)


# --------------------------------------------------------------------------
# Arm 2 -- the §11.4 carve-out. Bare `respawn` is the REMEDY, never refused.
# --------------------------------------------------------------------------
class TestBareRespawnStaysPermittedOverTheCeiling:
    """DO NOT "fix" this asymmetry into a uniform refusal.

    Bare `fleet respawn <name>` is how an over-band worker gets a fresh
    context. If the ceiling refused it, the fleet would reach 200k and have no
    way back down -- the guard would contain its own remedy in its refusal set
    (claim-nonce §7.2). These tests fail LOUD if that carve-out is ever closed.
    """

    def test_cmd_respawn_without_task_is_not_refused_by_the_ceiling(
            self, ceil_home, monkeypatch):
        # Past the ceiling the verb proceeds to its NEXT guard
        # (`_require_instance_settings`), which proves the ceiling did not stop
        # it. We assert the failure is NOT the ceiling's.
        _as_over_ceiling_holder(monkeypatch, occupancy=999999)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_respawn(_respawn_args(task=None))
        assert "11.3" not in str(ei.value)

    def test_cmd_respawn_native_without_task_is_not_refused_by_the_ceiling(
            self, ceil_home, monkeypatch):
        _as_over_ceiling_holder(monkeypatch, occupancy=999999)
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **kw: (False, []))
        before = {"session_id": "sid-old", "cwd": str(ceil_home), "mode": "acceptEdits"}
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet._cmd_respawn_native(_respawn_args(task=None), before)
        assert "11.3" not in str(ei.value)
        assert "roster" in str(ei.value)    # the next guard, reached

    def test_the_ceiling_predicate_is_never_even_consulted_without_a_task(
            self, ceil_home, monkeypatch):
        """Stronger than "no 11.3 in the message": the arming is what is pinned.

        A body that armed the ceiling unconditionally and then swallowed or
        reworded the refusal would still pass the two tests above. This one
        records that bare respawn does not ASK.
        """
        _as_over_ceiling_holder(monkeypatch, occupancy=999999)
        asked = []
        monkeypatch.setattr(fleet, "_ceiling_refuses_dispatch",
                            lambda verb, now=None: asked.append(verb))
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_respawn(_respawn_args(task=None))
        assert asked == [], (
            f"bare `respawn` consulted the 200k ceiling ({asked}) -- §11.4 "
            f"recovery must stay permitted over the ceiling, or the ceiling "
            f"is self-sealing (claim-nonce §7.2)")

    def test_a_task_bearing_respawn_DOES_consult_it(self, ceil_home, monkeypatch):
        # The seed for the test above: if the probe never fires either way, the
        # `asked == []` assertion passes vacuously.
        _as_over_ceiling_holder(monkeypatch, occupancy=999999)
        asked = []
        monkeypatch.setattr(fleet, "_ceiling_refuses_dispatch",
                            lambda verb, now=None: asked.append(verb))
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_respawn(_respawn_args(task="go"))
        assert asked == ["respawn"]


# --------------------------------------------------------------------------
# The census -- so the NEXT omission of this kind is loud.
# --------------------------------------------------------------------------
def _ceiling_call_sites():
    """(enclosing function, verb literal) for every `_ceiling_refuses_dispatch`
    CALL in `bin/fleet.py`, derived from the source by `ast` rather than by
    grep -- prose in this file mentions the name a dozen times and a line
    matcher would count docstrings as guards."""
    tree = ast.parse(Path(fleet.__file__).read_text(encoding="utf-8"))
    sites = []

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "_ceiling_refuses_dispatch"):
                verb = (child.args[0].value
                        if child.args and isinstance(child.args[0], ast.Constant)
                        else None)
                sites.append((owner, verb))
            visit(child, owner)

    visit(tree, None)
    return sites


class TestTheCeilingCallSiteCensus:
    def test_there_are_exactly_five_and_respawn_is_among_them(self):
        sites = _ceiling_call_sites()
        # Seed check: a rename or a re-spelling that this matcher misses would
        # make every assertion below pass vacuously.
        assert sites, "no `_ceiling_refuses_dispatch` call found at all -- matcher rotted"
        assert sorted(sites) == sorted([
            ("cmd_spawn", "spawn"),
            ("cmd_send", "send"),
            ("cmd_sup_spawn", "sup-spawn"),
            ("cmd_respawn", "respawn"),
            ("_cmd_respawn_native", "respawn"),
        ]), (
            f"the 200k ceiling's call sites changed: {sorted(sites)}. Adding a "
            f"dispatch verb without one is how `respawn` spent its first "
            f"lifetime outside the ceiling -- a supervisor dispatched a wave at "
            f"224,321 tokens through it. Removing one needs a ruling, not a "
            f"tidy-up.")

    def test_every_call_site_names_a_real_verb(self):
        for owner, verb in _ceiling_call_sites():
            assert verb, f"{owner} passes a non-literal verb to the ceiling"
