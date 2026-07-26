"""TASK 5 PIN 1 -- no `sup-*` verb mutates `state/fleet.json` on a corrupt registry.

THE DEFECT. `_acting_worker_identity` read the registry with

    try: registry = load_registry()
    except RegistryCorruptError: return ident

and `load_registry`'s own docstring says: *"corrupt/unreadable file is
quarantined (renamed aside) and raises RegistryCorruptError -- callers must
abort, not catch-and-continue."* The exception was swallowed; **the rename was
not**. `_require_claim_holder` calls the identity read at the very top, so on a
corrupt registry every one of its seven call sites -- `sup-checkpoint`,
`sup-heartbeat`, `sup-release`, `sup-decision`, `sup-handoff-begin`,
`sup-handoff-complete`, `sup-handoff-abort` -- silently renamed
`state/fleet.json` aside and then returned **rc=0, reporting success**.

Two facts make it worse than a stray rename. `sup-heartbeat` is the
highest-frequency supervisor verb there is and had no reason to read the
registry at all before this branch. And `sup-handoff-begin` is the one lever the
200k ceiling exempts -- so the branch arranged for the roster to be destroyed by
the exact command an over-ceiling supervisor is told to reach for.

WHY THE SUITE DID NOT CATCH IT (the §8 trap the break lens set): mutation M-X --
computing the role lazily -- left **2215 passed, 11 skipped**. Nothing in the
suite asserted whether the claim guard read the registry on the happy path, or
what that read did to the file. A mutation ledger proves the guards you thought
of are covered; it cannot prove a new read is side-effect-free. This file is
that missing assertion.

It is deliberately BEHAVIOURAL -- it drives the verbs and then looks at the
filesystem -- rather than a source-level check that the call is spelled
`_registry_records_or_none`. A future refactor that reintroduces the quarantine
by another spelling must go red here. `tests/test_load_registry_callers.py` is
the source-level companion that catches the same class one step earlier.
"""
import json
from types import SimpleNamespace

import pytest

import fleet


CORRUPT = "{ this is not json"


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """A sandboxed FLEET_HOME with a held claim, a live nonce, and a CORRUPT
    `state/fleet.json`. Nothing here touches the live fleet."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "supervisor"):
        (tmp_path / sub).mkdir(exist_ok=True)
    (tmp_path / "supervisor" / "GOALS.md").write_text(
        "# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
    return tmp_path


def _hold(sid="sid-sup"):
    """Write a held claim and return the plaintext of its LIVE generation."""
    value = fleet.mint_nonce()
    fleet.write_incarnation({
        "incarnation_id": "inc-x", "session_id": sid, "state": "active",
        "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 3,
        "lineage_id": "lin-x", "heartbeat_at": fleet.now_iso()})
    return value


def _corrupt(home):
    fleet.registry_path().write_text(CORRUPT, encoding="utf-8")


def _registry_untouched(home):
    """The whole assertion, in one place: the file is still there, still
    byte-identical, and no quarantine copy appeared beside it."""
    path = fleet.registry_path()
    assert path.exists(), "state/fleet.json was renamed aside by a supervisor verb"
    assert path.read_text(encoding="utf-8") == CORRUPT
    strays = sorted(p.name for p in path.parent.iterdir()
                    if p.name != "fleet.json" and p.name.startswith("fleet.json"))
    assert strays == [], f"quarantine copies appeared: {strays}"


# The seven `_require_claim_holder` call sites, covered BY CLASS rather than one
# test each: what differs between them is only the args they carry, and the read
# under test happens before any of that is looked at. `verb` is the label; the
# lambda is the drive.
VERBS = {
    "sup-checkpoint": lambda n: fleet.cmd_sup_checkpoint(
        SimpleNamespace(body="a checkpoint", kind="CHECKPOINT", sid="sid-sup", nonce=n)),
    "sup-heartbeat": lambda n: fleet.cmd_sup_heartbeat(
        SimpleNamespace(sid="sid-sup", nonce=n)),
    "sup-release": lambda n: fleet.cmd_sup_release(
        SimpleNamespace(reason="done", sid="sid-sup", nonce=n)),
    "sup-decision": lambda n: fleet.cmd_sup_decision(
        SimpleNamespace(question="which way?", answer=None, clear=False,
                        sid="sid-sup", nonce=n)),
    "sup-handoff-begin": lambda n: fleet.cmd_sup_handoff_begin(
        SimpleNamespace(sid="sid-sup", nonce=n, model=None, permission_mode=None),
        which=lambda _x: None, run=None),
    "sup-handoff-complete": lambda n: fleet.cmd_sup_handoff_complete(
        SimpleNamespace(sid="sid-sup", nonce=n, expect_sid="sid-successor")),
    "sup-handoff-abort": lambda n: fleet.cmd_sup_handoff_abort(
        SimpleNamespace(sid="sid-sup", nonce=n, successor_sid="sid-successor"),
        which=lambda _x: None, run=None),
}


class TestNoSupervisorVerbQuarantinesTheRegistry:

    @pytest.mark.parametrize("verb", sorted(VERBS))
    def test_the_verb_leaves_a_corrupt_registry_exactly_as_it_found_it(
            self, sup_home, capsys, verb):
        nonce = _hold()
        _corrupt(sup_home)
        try:
            VERBS[verb](nonce)
        except fleet.FleetCliError:
            # Several of these legitimately refuse for reasons of their own on
            # a bare FLEET_HOME (no HANDSHAKE, no `claude` on PATH). The
            # refusal is not what is under test -- what the identity read did
            # to the file on the way there is.
            pass
        finally:
            capsys.readouterr()
        _registry_untouched(sup_home)

    def test_the_highest_frequency_verb_also_still_SUCCEEDS(self, sup_home, capsys):
        """`sup-heartbeat` is the beat, and it had no reason to read the
        registry before this branch. A corrupt registry must cost it nothing:
        not the file, and not the beat."""
        nonce = _hold()
        _corrupt(sup_home)
        assert fleet.cmd_sup_heartbeat(SimpleNamespace(sid="sid-sup", nonce=nonce)) == 0
        capsys.readouterr()
        _registry_untouched(sup_home)
        assert fleet.read_incarnation()["heartbeat_at"]

    def test_the_ceiling_exempt_lever_does_not_shred_the_roster(
            self, sup_home, capsys):
        """`sup-handoff-begin` is the one lever the 200k ceiling exempts -- the
        command an over-ceiling supervisor is explicitly told to reach for. It
        is the worst possible place to lose the roster."""
        nonce = _hold()
        _corrupt(sup_home)
        with pytest.raises(fleet.FleetCliError):
            # `claude` is deliberately absent from PATH here: the pre-flight
            # refusal happens AFTER the claim guard, which is the read at issue.
            fleet.cmd_sup_handoff_begin(
                SimpleNamespace(sid="sid-sup", nonce=nonce, model=None,
                                permission_mode=None),
                which=lambda _x: None, run=None)
        capsys.readouterr()
        _registry_untouched(sup_home)

    def test_a_HEALTHY_registry_is_not_rewritten_by_the_identity_read_either(
            self, sup_home, capsys):
        """The happy-path half of the same question, and the one M-X proved
        nothing about: a read is a read. Byte-compared, so a re-serialisation
        that merely happens to round-trip today still shows up the day a field
        is added."""
        nonce = _hold()
        fleet.save_registry({"workers": {"w1": {"session_id": "sid-w1",
                                                "retired_sids": [], "status": "idle"}}})
        before = fleet.registry_path().read_bytes()
        assert fleet.cmd_sup_heartbeat(SimpleNamespace(sid="sid-sup", nonce=nonce)) == 0
        capsys.readouterr()
        assert fleet.registry_path().read_bytes() == before

    def test_the_seven_call_sites_are_all_covered(self):
        """The seed check. If a verb is added to `_require_claim_holder`'s
        callers and not to `VERBS`, the parametrisation above silently stops
        being a claim about all of them -- which is exactly the shape of defect
        this file was written to catch."""
        import re
        from pathlib import Path
        src = Path(fleet.__file__).read_text(encoding="utf-8")
        cited = set(re.findall(r'verb="(sup-[a-z-]+)"', src))
        assert cited, "no `verb=\"sup-...\"` labels found -- the matcher rotted"
        assert cited == set(VERBS), (
            f"uncovered `_require_claim_holder` verbs: {sorted(cited - set(VERBS))}; "
            f"covered verbs that no longer exist: {sorted(set(VERBS) - cited)}")
