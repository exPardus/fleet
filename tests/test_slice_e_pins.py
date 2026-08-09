"""Multi-fleet slice (e) -- the §7 test-isolation pins that slice (a) did not
ship, and the two it shipped that cannot fail.

WHAT THIS FILE OWES, MEASURED RATHER THAN READ (`docs/lanes/w51-slicee.md` §1).
§7 names ten pin categories. Six are landed and non-vacuous -- a planted mutant
reddens each. This file covers the other four:

  1. **the env fixture** -- `tests/conftest.py`'s autouse home sandbox
     enumerated THREE helpers by name and `homes_list_path` was not one of
     them, so the redirect existed only as four file-scoped copies and every
     other test file read the operator's real `~/.claude/fleet-homes.list`.
     Measured before the fix: 19 calls resolved to the real path across
     `test_cli.py`, `test_view_quarantine.py` and `test_supervisor.py` alone,
     and 0 to a sandbox.
  3. **the real-list-untouched pin** -- it existed by name
     (`test_home_resolution.py::test_the_real_list_is_untouched`) and was a
     tautology: it compared `REAL_LIST.exists()` before and after ONE READ,
     under an autouse sandbox, so it could not reach the real list and could
     not have seen an append if it had. Mutants that appended 122 and 117
     records to a simulated real list left it green.
  4. **the quiescent-home canary** -- never built. Zero occurrences of
     `quiescent` under `tests/`.
  7. is repaired in place, in `test_homes_list.py`, because that is where the
     lint lives.

WHY SLICE (a) DID NOT SHIP 1 AND 3, IN ITS OWN WORDS. `test_homes_list.py`'s
module docstring: *"Editing `conftest.py` is outside this lane's fence, so the
redirect lives here as an autouse fixture with a seed ... §7's
'real-list-untouched pin' wants the conftest half; that is escalated in the a1
report."* This file and the conftest edit beside it are that escalation
discharged.

WHAT THIS FILE DELIBERATELY DOES NOT DEFINE: its own `sandboxed_list` fixture.
That absence is load-bearing -- `TestTheConftestRedirectReachesEveryFile` is
only meaningful in a file that does NOT opt in, because what it pins is the
DEFAULT.
"""
import hashlib
import json
from pathlib import Path

import pytest

import fleet
from conftest import (homes_list_drift, homes_list_snapshot,
                      real_homes_list_path)

REAL_LIST = Path.home() / ".claude" / "fleet-homes.list"


# ---------------------------------------------------------------------------
# Category 1 -- the env fixture. The DEFAULT, not the opt-in.
# ---------------------------------------------------------------------------

class TestTheConftestRedirectReachesEveryFile:
    """§7's *"env fixture"*, which is the half slice a1 could not build.

    This class asserts a property of `tests/conftest.py`, from a file that
    defines no `sandboxed_list` of its own. If the conftest redirect is
    removed, every test here goes RED -- which is the point: the four
    file-scoped copies would still be green, and their greenness is exactly
    what hid the gap."""

    def test_the_default_homes_list_path_is_not_the_real_one(self):
        assert fleet.homes_list_path() != REAL_LIST, (
            "a test file that does not opt into a sandbox resolved the "
            "operator's real homes list. `tests/conftest.py` must redirect "
            "`homes_list_path` the way it redirects the other home-derived "
            "helpers.")

    def test_the_default_lands_inside_the_conftest_home_sandbox(self):
        """Not merely *"not the real one"*: in the SAME sandbox as the other
        three helpers, so a future home-plane path added to fleet lands there
        by default instead of needing to be remembered separately -- which is
        the property conftest's docstring claims and did not have."""
        got = fleet.homes_list_path()
        settings = fleet.user_settings_path()
        assert got.parent == settings.parent, (
            f"{got} is redirected but not into the home sandbox at "
            f"{settings.parent}")
        assert got.name == REAL_LIST.name

    def test_reading_the_default_creates_nothing(self):
        """The no-`mkdir` rule, re-asserted at the redirect: a sandboxed read
        must not manufacture a list, or every unsandboxed test would start
        looking like a multi-fleet machine."""
        path = fleet.homes_list_path()
        assert not path.exists()
        out = fleet.read_homes_list()
        assert (out["ok"], out["reason"], out["members"]) == (True, "absent", [])
        assert not path.exists()

    def test_a_write_through_the_default_lands_in_the_sandbox(self):
        """The read side being redirected is not the dangerous half. This is:
        an unsandboxed test that reaches a WRITER must not append to the
        machine-global list, which is RATIFIED DESTRUCTIVE and which only the
        fold reverses.

        THE ASSERTION IS BEFORE THE WRITE, DELIBERATELY. A pin whose FAILING
        path performs the act it is pinning against is a pin that damages the
        machine every time it goes RED -- and this one's RED state is exactly
        *"the redirect is missing"*, i.e. exactly when the append would land in
        the operator's real list. The guard runs first and the write is
        unreachable until it passes."""
        target = fleet.homes_list_path()
        real = real_homes_list_path()
        assert target != real, (
            "refusing to exercise the writer: `homes_list_path()` resolves to "
            "the operator's real list, so this test's own append would be the "
            "destructive act it exists to forbid")
        before = homes_list_snapshot(real)
        fleet.append_home_record("C:/w51-slicee-canary")
        assert target.exists()
        assert "C:/w51-slicee-canary" in fleet.read_homes_list()["members"]
        assert homes_list_drift(real, before) is None


# ---------------------------------------------------------------------------
# Category 3 -- the real-list-untouched pin, made able to fail.
# ---------------------------------------------------------------------------

class TestTheRealListGuardCanActuallySeeAChange:
    """THE SEEDS for `conftest._the_real_homes_list_is_untouched_afterwards`.

    The guard is a before/after comparison over a file that is expected never
    to change, which is the exact shape that passes vacuously when the
    comparison rots -- and the pin it replaces was vacuous in four independent
    ways at once (`docs/lanes/w51-slicee.md` §3.1). Its helpers are therefore
    module-level and parameterised on `path`, the same shape `code_plane_files`
    already uses for the install-plane guard, so these seeds can drive them
    against a file they are allowed to modify.

    THREE SHAPES, NOT ONE. The pin this replaces checked `exists()` only, so it
    was blind to the single write the list's own writer can perform. An append
    is pinned first for that reason."""

    def test_an_append_is_seen(self, tmp_path):
        """THE ONE THAT MATTERS. `append_home_record` is the only writer, and
        `exists()` does not move when it runs."""
        path = tmp_path / "fleet-homes.list"
        path.write_text("C:/a\n", encoding="utf-8")
        before = homes_list_snapshot(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("C:/b\n")
        drift = homes_list_drift(path, before)
        assert drift is not None, "an append was invisible to the guard"
        assert drift[0][0] is drift[1][0] is True, "existence did not move"
        assert drift[0][2] != drift[1][2], "the size did not move either"

    def test_a_creation_is_seen(self, tmp_path):
        path = tmp_path / "fleet-homes.list"
        before = homes_list_snapshot(path)
        assert before[0] is False
        path.write_text("C:/a\n", encoding="utf-8")
        assert homes_list_drift(path, before) is not None

    def test_a_deletion_is_seen(self, tmp_path):
        path = tmp_path / "fleet-homes.list"
        path.write_text("C:/a\n", encoding="utf-8")
        before = homes_list_snapshot(path)
        path.unlink()
        assert homes_list_drift(path, before) is not None

    def test_an_in_place_edit_of_the_same_length_is_seen(self, tmp_path):
        """The size half of the tuple would miss this; the digest is what
        catches a rewrite that folds the list to the same byte count."""
        path = tmp_path / "fleet-homes.list"
        path.write_text("C:/a\nC:/b\n", encoding="utf-8")
        before = homes_list_snapshot(path)
        path.write_text("C:/b\nC:/a\n", encoding="utf-8")
        after = homes_list_snapshot(path)
        assert before[2] == after[2], "this seed no longer holds length equal"
        assert homes_list_drift(path, before) is not None

    def test_no_change_is_no_drift(self, tmp_path):
        """The other direction, so the guard cannot pass its seeds by
        answering *"changed"* to everything."""
        path = tmp_path / "fleet-homes.list"
        path.write_text("C:/a\n", encoding="utf-8")
        before = homes_list_snapshot(path)
        path.read_bytes()
        assert homes_list_drift(path, before) is None

    def test_the_guard_asks_the_real_home_not_the_redirected_helper(self):
        """`real_homes_list_path()` must NOT be `fleet.homes_list_path()`.

        The redirect is autouse, so a guard that asked fleet for the path would
        hash the sandbox -- it would protect the tmp file and ignore the file
        it exists for. This is the same defect as the pin it replaces, one
        level down, and it is the one an adversarial reader should look for."""
        assert real_homes_list_path() == REAL_LIST
        assert real_homes_list_path() != fleet.homes_list_path()

    def test_an_unreadable_real_list_is_a_state_not_a_crash(self, tmp_path):
        """A session-scoped guard that raises on a permission error takes the
        whole suite down at teardown. Directory-as-file is the shape §4's
        `list_unreadable` reason already names."""
        path = tmp_path / "fleet-homes.list"
        path.mkdir()
        snap = homes_list_snapshot(path)
        assert snap[0] is True and str(snap[1]).startswith("<unreadable")
        assert homes_list_drift(path, snap) is None


# ---------------------------------------------------------------------------
# Category 4 -- the quiescent-home canary.
# ---------------------------------------------------------------------------

def _home(root, name, workers=None):
    h = root / name
    (h / "state").mkdir(parents=True)
    (h / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers or {}}), encoding="utf-8")
    return h


def _digest(root):
    """Byte digest of a whole home, `files=` included.

    The count is not decoration: it is what catches a run that DELETED a file,
    which a content-only hash over the surviving files would miss. Same
    argument as `docs/lanes/BRIEF-TEMPLATE.md`'s working-tree digest, which
    this deliberately mirrors."""
    h, n = hashlib.sha256(), 0
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        h.update(p.relative_to(root).as_posix().encode("utf-8"))
        h.update(hashlib.sha256(p.read_bytes()).digest())
        n += 1
    return f"{h.hexdigest()} files={n}"


def home_is_quiescent(home):
    """No record in this home could plausibly BE an acting body right now.

    Reuses `fleet._record_is_live`, the repo's one spelling of *"live"*
    (`bin/fleet.py`: not archived, not marked dead), rather than re-deriving
    it: a second spelling is how a canary starts disagreeing with the code it
    is watching. Unreadable is NOT quiescent -- indeterminacy never selects the
    permissive branch (§5's Arming paragraph), and here the permissive branch
    is *"assert nothing changed"* over a home we cannot read."""
    ok, _reason, data = fleet.read_registry_at(fleet.home_identity(home))
    if not ok:
        return False
    return not any(fleet._record_is_live(rec)
                   for rec in data["workers"].values())


class TestTheQuiescentHomeCanary:
    """§7, verbatim: *"quiescent-home canary with loud skip,
    delete-if-never-quiescent"*.

    WHAT IT ASSERTS: driving a fleet in home A leaves every OTHER listed home
    BYTE-IDENTICAL. That is the *"Zero cross-home writes"* line of M1's scope
    and the `fleet.lock`, registry, mailbox, claims row of the cross-fleet
    interference audit, turned into something that runs.

    WHY IT IS SCOPED TO QUIESCENT HOMES, which is the clause §7 spells out and
    does not explain: a home with a live body in it mutates on its own -- a
    Stop hook appends an outcome, a heartbeat restamps -- so a byte comparison
    over it measures the other fleet's liveness, not this fleet's interference.
    The canary would be flaky in exactly the situation it is most wanted.

    THE LOUD SKIP, AND WHY IT IS LOUD. A skip that says only *"skipped"* is
    indistinguishable from a pass at a glance, and this repo has been burned by
    a canary reading green over a hole. The skip names the home and the reason.

    `delete-if-never-quiescent`, DISCHARGED BY CONSTRUCTION RATHER THAN BY
    POLICY. §7 asks for the canary to be deleted if it never finds a quiescent
    home, because a permanently-skipping test is worse than no test. Rather
    than police that with a counter nobody reads, the fixture below BUILDS the
    quiescent home, so the asserting arm is reachable on every run of every
    machine, and `test_the_quiescent_arm_is_reachable_by_construction` is what
    fails if that ever stops being true. The skip arm still exists and is still
    exercised -- it is what a real non-quiescent home would take."""

    @pytest.fixture
    def two_homes(self, tmp_path, monkeypatch):
        """A (the fleet we drive) and B (the bystander), both listed.

        THE GUARD BEFORE THE WRITE IS NOT DEFENSIVE PROGRAMMING, IT IS A
        MEASURED REPAIR. The first RED run of this file wrote the homes list
        through `fleet.homes_list_path()` before the conftest redirect existed
        -- so the fixture that exists to prove nothing touches a foreign home
        created `~/.claude/fleet-homes.list` itself. It was caught by the
        session guard added in the same commit, at teardown, on its first run;
        it was contained because the run was fenced with a throwaway
        `USERPROFILE`. A fixture that writes a machine-global path must assert
        the path is not the machine's before it writes, because the moment its
        sandbox is missing is exactly the moment it runs."""
        target = fleet.homes_list_path()
        assert target != real_homes_list_path(), (
            "refusing to build the canary's homes list: `homes_list_path()` "
            "resolves to the operator's real list. This fixture writes it.")
        a = _home(tmp_path, "A")
        b = _home(tmp_path, "B")
        (b / "logs").mkdir()
        (b / "logs" / "worker.log").write_text("bystander\n", encoding="utf-8")
        (b / "mailbox").mkdir()
        target.write_text(
            f"{fleet.home_identity(a)}\n{fleet.home_identity(b)}\n",
            encoding="utf-8")
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        return a, b

    def test_the_quiescent_arm_is_reachable_by_construction(self, two_homes):
        """`delete-if-never-quiescent`, as an assertion. If the bystander stops
        being quiescent, every canary below degrades to a skip and this is the
        RED that says so instead of letting the file go quietly green."""
        _a, b = two_homes
        assert home_is_quiescent(b), (
            "the canary's own bystander is not quiescent, so its asserting arm "
            "is unreachable and the canary has become a permanent skip -- "
            "delete it or fix the fixture (§7: delete-if-never-quiescent)")

    @pytest.mark.parametrize("argv", [
        ["status"],
        ["homes"],
        ["clean", "--yes"],
        ["home"],
    ])
    def test_driving_home_a_leaves_home_b_byte_identical(
            self, argv, two_homes, monkeypatch, capsys):
        a, b = two_homes
        if not home_is_quiescent(b):
            pytest.skip(
                f"LOUD SKIP: bystander home {b} is not quiescent -- it holds a "
                f"live record, so a byte comparison over it would measure that "
                f"fleet's own activity rather than this one's interference. "
                f"§7 scopes the canary to quiescent homes for this reason.")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        before = _digest(b)
        fleet.main(["--fleet-home", str(a)] + argv)
        capsys.readouterr()
        assert _digest(b) == before, (
            f"`fleet {' '.join(argv)}` driven against home A changed bystander "
            f"home B. M1's scope is *'Zero cross-home writes'*.")

    def test_the_canary_can_see_a_perturbation(self, two_homes):
        """THE SEED. The assertion above is *"nothing changed"*, which is the
        shape that passes when the digest stops looking. Perturb B in each of
        the three ways a wrong-home verb actually would -- append, rewrite,
        DELETE -- and prove the comparison reddens for all three. The delete is
        why `files=` is in the digest."""
        _a, b = two_homes
        before = _digest(b)

        (b / "logs" / "worker.log").write_text("perturbed\n", encoding="utf-8")
        assert _digest(b) != before, "a rewrite inside B was invisible"

        (b / "logs" / "worker.log").write_text("bystander\n", encoding="utf-8")
        assert _digest(b) == before, "the digest is not stable under restore"

        (b / "state" / "extra.json").write_text("{}", encoding="utf-8")
        assert _digest(b) != before, "a new file in B was invisible"
        (b / "state" / "extra.json").unlink()

        (b / "logs" / "worker.log").unlink()
        assert _digest(b) != before, (
            "a DELETION inside B was invisible -- this is what `files=` is in "
            "the digest for")

    def test_a_live_bystander_takes_the_skip_arm(self, tmp_path, monkeypatch):
        """The skip arm, exercised rather than merely written. A home holding a
        live record must be classified NOT quiescent, or the canary would
        assert byte-equality over a fleet that is running."""
        live = _home(tmp_path, "LIVE", workers={
            "w": {"session_id": "s-1", "status": "running",
                  "archived_at": None, "retired_sids": []}})
        assert not home_is_quiescent(live)

    @pytest.mark.parametrize("status,archived,quiescent", [
        ("dead", None, True),
        ("idle", None, False),
        ("running", None, False),
        ("idle", "2026-08-09T00:00:00Z", True),
    ])
    def test_quiescence_is_the_repos_own_spelling_of_live(
            self, status, archived, quiescent, tmp_path):
        """Pinned against `fleet._record_is_live` rather than against a list of
        status words this file invented. A record is live unless it is archived
        or marked dead -- so an IDLE worker is live, and a canary that treated
        `idle` as quiescent would assert byte-equality over a home whose Stop
        hook can still fire."""
        h = _home(tmp_path, f"h-{status}-{bool(archived)}", workers={
            "w": {"session_id": "s", "status": status,
                  "archived_at": archived, "retired_sids": []}})
        assert home_is_quiescent(h) is quiescent

    def test_an_unreadable_home_is_not_quiescent(self, tmp_path):
        """Indeterminacy never selects the permissive branch (§5's Arming
        paragraph). Here the permissive branch is asserting byte-equality over
        a home whose state nobody could read."""
        h = tmp_path / "corrupt"
        (h / "state").mkdir(parents=True)
        (h / "state" / "fleet.json").write_bytes(b"\x00\xff not json")
        assert not home_is_quiescent(h)
