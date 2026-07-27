"""THE CORRUPT->ABSENT CONVERSION: fleet's own repair verb opened the §9 door.

THE DEFECT, driven end to end (gate reviewer, 2026-07-27). Fix wave 2 closed the
§9 legacy upgrade against an ABSTAINING registry -- a corrupt `state/fleet.json`
makes `_acting_body_is_worker_turn` return None, and the upgrade arm demands an
affirmative False because it is the one arm that mints generation 1 on bare sid
equality with no generation presented. What it did not close is that the two
registry states are not independent hazards, they are a SEQUENCE:

  1. corrupt registry  -> `sup-heartbeat` REFUSES, and the refusal text says
     *"Repair `state/fleet.json` (see `fleet doctor`)"*.
  2. `fleet doctor`    -> `_quarantine_registry` RENAMES the file aside to
     `state/fleet.json.corrupt.<ts>`, leaving NO `state/fleet.json` behind.
  3. the SAME command  -> rc 0, `nonce_seq == 1`, a `NONCE:` printed, and no
     `--nonce` was ever passed.

The refusal message names the command that opens the door. Absent was an
AFFIRMATIVE answer (`reason == "not_initialized"` counted as a successful read,
because *"the file does not exist yet"* is a definite *"there are no records"*),
so the repair converted the abstention into the affirmative verdict the arm was
waiting for.

THE REMEDY IS NOT *"make absent abstain"*. That closes the FRESH-INSTALL
carve-out, which is load-bearing: mutant W11 measured it refusing the §9 upgrade
on every fresh install and killing 39 tests. Absent must stay affirmative when it
means *"nothing has ever been written here"*.

The remedy is the QUARANTINE ARTIFACT GLOB, already this file's established
spelling for *"a registry was corrupt moments ago and the next load sees a
MISSING file"* (`_husk_sweep_refuses`, `_doctor_check_autoclean`). Absent with no
artifact beside it = a fresh install => affirmative. Absent WITH an artifact =
the corrupt state under a new name => abstain, exactly as corrupt does.

`TestTheThreeStepRepro` is the defect itself as a test.
`TestTheFreshInstallCarveOutSurvives` is the test that stops the obvious wrong fix.
"""
import json
from types import SimpleNamespace

import pytest

import fleet


CORRUPT = "{ this is not json"

# The name `_quarantine_registry` actually mints: `now_iso()` with the colons
# stripped. Written literally here rather than derived, so a change to the
# artifact's SPELLING has to break this file deliberately.
ARTIFACT = "fleet.json.corrupt.2026-07-27T000000Z"


@pytest.fixture
def qg_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME -- same shape as `tests/test_identity_fixwave2.py`'s
    `id2_home`. Nothing here touches the live fleet."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir(exist_ok=True)
    (tmp_path / "supervisor" / "GOALS.md").write_text(
        "# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge" / "INDEX.md").write_text(
        "# Knowledge Index\n- entry one\n", encoding="utf-8")
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return tmp_path


def _rec(session_id=None, retired=(), status="idle", archived_at=None):
    return {"session_id": session_id, "retired_sids": list(retired),
            "status": status, "archived_at": archived_at}


def _registry(workers):
    fleet.save_registry({"workers": workers})


def _corrupt():
    fleet.registry_path().write_text(CORRUPT, encoding="utf-8")


def _quarantine(name=ARTIFACT):
    """`_quarantine_registry`'s effect, applied DIRECTLY: rename the registry
    aside, leaving no `state/fleet.json`.

    Deliberately not a shell-out to `fleet doctor` -- the assertion is about the
    STATE doctor leaves behind, and coupling this file to doctor's exit code
    would make an unrelated doctor row able to rot the repro."""
    fleet.registry_path().rename(fleet.state_dir() / name)
    return fleet.state_dir() / name


def _legacy(sid):
    """The §9 legacy INCARNATION: five keys, no `nonce_hash`, no `state`."""
    fleet.write_incarnation({
        "incarnation_id": "inc-legacy", "session_id": sid, "lineage_id": "lin-x",
        "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso()})


def _beat(sid, nonce=None):
    return fleet.cmd_sup_heartbeat(SimpleNamespace(sid=sid, nonce=nonce))


# --------------------------------------------------------------------------
# 1. The three-step repro, as a test
# --------------------------------------------------------------------------

class TestTheThreeStepRepro:
    """Step 1 refuses today. Step 3 is the defect: the same call, after the
    remedy fleet's OWN refusal text prescribed, succeeds."""

    def test_step_1_a_corrupt_registry_REFUSES_the_upgrade(self, qg_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        _legacy("sid-w1")
        _corrupt()
        with pytest.raises(fleet.FleetCliError) as exc:
            _beat("sid-w1")
        assert "registry" in str(exc.value)
        assert "nonce_hash" not in fleet.read_incarnation()

    def test_step_3_the_QUARANTINED_registry_MUST_STILL_REFUSE(
            self, qg_home, monkeypatch, capsys):
        """THE DEFECT. Before the fix this call returns 0, prints a `NONCE:` and
        writes `nonce_seq == 1` -- with no `--nonce` ever passed -- because the
        rename turned `unreadable` into `not_initialized` and the resolver
        counted that as an affirmative *"you are not a worker"*."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        _legacy("sid-w1")
        _corrupt()
        with pytest.raises(fleet.FleetCliError):
            _beat("sid-w1")                      # step 1
        artifact = _quarantine()                 # step 2 -- what doctor leaves
        assert not fleet.registry_path().exists()
        assert artifact.exists()
        with pytest.raises(fleet.FleetCliError) as exc:   # step 3
            _beat("sid-w1")
        assert "registry" in str(exc.value)
        claim = fleet.read_incarnation()
        assert "nonce_hash" not in claim
        assert "nonce_seq" not in claim
        assert "NONCE:" not in capsys.readouterr().out

    def test_the_refusal_does_not_send_the_operator_back_to_doctor_alone(
            self, qg_home, monkeypatch):
        """`fleet doctor` is what MADE this state, and the generic abstention
        note names it as the remedy. Running it again finds nothing to repair,
        so the refusal has to say what the artifact means and how to get out."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        _legacy("sid-w1")
        _corrupt()
        artifact = _quarantine()
        with pytest.raises(fleet.FleetCliError) as exc:
            _beat("sid-w1")
        msg = str(exc.value)
        assert artifact.name in msg
        assert "restore the quarantined file" in msg

    def test_a_still_CORRUPT_registry_keeps_the_plain_note(self, qg_home, monkeypatch):
        """An artifact from an EARLIER incident must not relabel a registry that
        is present and broken right now: that one really is *"could not be
        read"*, and `fleet doctor` really is its remedy."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        _legacy("sid-w1")
        _corrupt()
        with pytest.raises(fleet.FleetCliError) as exc:
            _beat("sid-w1")
        assert "state/fleet.json could not be read" in str(exc.value)

    def test_the_predicate_ABSTAINS_on_absent_plus_artifact(self, qg_home):
        """The tri-state underneath, so a later refactor of the arm cannot lose
        the rule silently. Corrupt is None; corrupt-then-renamed must be None
        too, not the False that absent-alone earns."""
        _registry({"w1": _rec("sid-w1")})
        _corrupt()
        assert fleet._acting_body_is_worker_turn(sid="sid-nobody") is None
        _quarantine()
        assert fleet._acting_body_is_worker_turn(sid="sid-nobody") is None

    def test_the_identity_resolver_reports_the_read_as_NOT_taken(self, qg_home):
        """`registry_read` is the bit fix wave 2 added and the bit every
        consumer keys off. Absent-plus-artifact must clear it."""
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        ident = fleet._acting_worker_identity(sid="sid-nobody")
        assert ident["registry_read"] is False
        assert ident["verdict"] == fleet.IDENTITY_UNRESOLVED


# --------------------------------------------------------------------------
# 2. The carve-out that must NOT close
# --------------------------------------------------------------------------

class TestTheFreshInstallCarveOutSurvives:
    """DO NOT CLOSE THE CARVE-OUT. Making `not_initialized` abstain
    unconditionally is the obvious fix and it is wrong: mutant W11 measured it
    refusing the §9 upgrade on every fresh install, 39 tests dead. An absent
    registry with NO artifact beside it is *"nothing was ever written here"* --
    a definite *"there are no records"*, which is an affirmative answer."""

    def test_a_fresh_install_STILL_earns_the_upgrade(
            self, qg_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        assert not fleet.registry_path().exists()
        assert not list(fleet.state_dir().glob("fleet.json.corrupt.*"))
        _legacy("sid-iface")
        assert _beat("sid-iface") == 0
        assert "NONCE:" in capsys.readouterr().out
        assert fleet.read_incarnation()["nonce_seq"] == 1

    def test_the_predicate_on_a_fresh_install_is_still_an_affirmative_False(
            self, qg_home):
        assert not fleet.registry_path().exists()
        assert fleet._acting_body_is_worker_turn(sid="sid-nobody") is False

    def test_unrelated_files_in_state_do_not_fire_the_abstention(self, qg_home):
        """The glob is `fleet.json.corrupt.*`, not `fleet.json*` and not `*`. A
        state dir is FULL of files -- `events.jsonl`, `worker-settings.json`, a
        `.bak`, the tmp file an atomic write leaves on a crash -- and none of
        them is evidence that a registry was quarantined."""
        for name in ("events.jsonl", "fleet.json.bak", "fleet.json.tmp",
                     "corrupt.fleet.json", "fleet.jsonl", "INCARNATION.bak"):
            (fleet.state_dir() / name).write_text("x", encoding="utf-8")
        assert not fleet.registry_path().exists()
        assert fleet._acting_body_is_worker_turn(sid="sid-nobody") is False

    def test_the_glob_reads_state_dir_NOT_the_process_cwd(
            self, qg_home, monkeypatch, capsys):
        """An artifact-shaped name that is not IN `state/` proves nothing. Pinned
        because the natural typo -- `Path().glob(...)` instead of
        `state_dir().glob(...)` -- reads the process cwd, which under pytest is
        the repo root and under a worker is the project dir."""
        (qg_home / ARTIFACT).write_text(CORRUPT, encoding="utf-8")   # FLEET_HOME root
        monkeypatch.chdir(qg_home)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _legacy("sid-iface")
        assert fleet._acting_body_is_worker_turn(sid="sid-iface") is False
        assert _beat("sid-iface") == 0
        capsys.readouterr()
        assert fleet.read_incarnation()["nonce_seq"] == 1


# --------------------------------------------------------------------------
# 3. The edges of the glob
# --------------------------------------------------------------------------

class TestTheGlobsEdges:

    def test_MULTIPLE_artifacts_still_abstain(self, qg_home, monkeypatch):
        """Repeated corruption leaves a pile. The rule is presence, not count --
        `_husk_sweep_refuses` takes the same presence-only reading, and for the
        same reason: `os.rename` preserves mtime, so nothing useful can be
        concluded from which artifact is newest."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1")})
        _quarantine("fleet.json.corrupt.2026-07-25T000000Z")
        for name in ("fleet.json.corrupt.2026-07-26T000000Z", ARTIFACT):
            (fleet.state_dir() / name).write_text(CORRUPT, encoding="utf-8")
        _legacy("sid-w1")
        with pytest.raises(fleet.FleetCliError) as exc:
            _beat("sid-w1")
        assert "registry" in str(exc.value)
        assert "nonce_hash" not in fleet.read_incarnation()

    def test_an_artifact_beside_a_VALID_registry_does_NOT_interfere(
            self, qg_home, monkeypatch, capsys):
        """THE GLOB GATES `not_initialized` ONLY. A healthy read is `ok` and
        answers for itself; an operator who has restored `state/fleet.json` but
        not yet deleted the artifact (the exact state `_husk_sweep_refuses`
        tells them to clean up, and it can outlive the incident by days) must
        not be locked out of the §9 upgrade by a stale file."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _registry({"w1": _rec("sid-w1")})
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        assert fleet.registry_path().exists()
        _legacy("sid-iface")
        assert fleet._acting_body_is_worker_turn(sid="sid-iface") is False
        assert _beat("sid-iface") == 0
        assert "NONCE:" in capsys.readouterr().out
        assert fleet.read_incarnation()["nonce_seq"] == 1

    def test_an_artifact_beside_a_valid_registry_still_RESOLVES_a_worker(
            self, qg_home, monkeypatch):
        """The other half of the same rule: the artifact must not degrade a
        healthy read into an abstention that would let a WORKER through the
        §6.5 gate. A worker turn stays True."""
        _registry({"w1": _rec("sid-w1", status="working")})
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        assert fleet._acting_body_is_worker_turn(sid="sid-w1") is True

    def test_an_artifact_does_not_brick_the_6_5_gate_on_a_HELD_claim(
            self, qg_home, monkeypatch, capsys):
        """The change is scoped to the §9 arm's threshold. The §6.5 gate reads
        the same tri-state at a different one -- it refuses on True ALONE -- so
        an abstention still passes it, and a holder presenting a live
        generation against a quarantined registry keeps working. Failing closed
        here would brick the release that ends the incident."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        value = fleet.mint_nonce()
        fleet.write_incarnation({
            "incarnation_id": "inc-x", "session_id": "sid-sup", "state": "active",
            "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 3,
            "lineage_id": "lin-x", "heartbeat_at": fleet.now_iso()})
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        assert not fleet.registry_path().exists()
        assert _beat("sid-sup", nonce=value) == 0
        capsys.readouterr()

    def test_the_artifact_check_never_writes_and_never_creates_state_dir(
            self, qg_home):
        """The resolver runs on the dispatch hot path, inside
        `_require_claim_holder` and inside a doctor row: read-only is a promise
        it already makes. A glob that materialised a directory would break it."""
        import shutil
        shutil.rmtree(fleet.state_dir())
        assert fleet._acting_body_is_worker_turn(sid="sid-nobody") is False
        assert not fleet.state_dir().exists()


# --------------------------------------------------------------------------
# 4. The helper itself -- ONE spelling of the artifact glob
# --------------------------------------------------------------------------

class TestTheArtifactGlobHelper:
    """`fleet.json.corrupt.*` was already spelled twice in `bin/fleet.py` for
    the same question. A third inline copy is how two of them drift apart, so
    the rule is named once and the existing sites read it."""

    def test_it_finds_the_artifacts_sorted(self, qg_home):
        for name in (ARTIFACT, "fleet.json.corrupt.2026-07-25T000000Z"):
            (fleet.state_dir() / name).write_text(CORRUPT, encoding="utf-8")
        found = [p.name for p in fleet._quarantine_artifacts()]
        assert found == ["fleet.json.corrupt.2026-07-25T000000Z", ARTIFACT]

    def test_it_is_empty_on_a_clean_state_dir(self, qg_home):
        (fleet.state_dir() / "fleet.json.bak").write_text("x", encoding="utf-8")
        assert fleet._quarantine_artifacts() == []

    def test_it_is_empty_rather_than_raising_when_state_dir_is_gone(self, qg_home):
        import shutil
        shutil.rmtree(fleet.state_dir())
        assert fleet._quarantine_artifacts() == []

    def test_the_glob_string_is_written_once_in_the_source(self):
        """A lint, not a behaviour test: `bin/fleet.py` must contain the literal
        glob pattern exactly once -- inside the helper."""
        src = (fleet.Path(fleet.__file__)).read_text(encoding="utf-8")
        assert src.count('"fleet.json.corrupt.*"') == 1
