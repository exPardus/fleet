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
MISSING file"* (`_sweep_husks`, `_doctor_check_autoclean`). Absent with no
artifact beside it = a fresh install => affirmative. Absent WITH an artifact =
the corrupt state under a new name => abstain, exactly as corrupt does.

AND THAT ALONE IS NOT ENOUGH -- keying on registry-file ABSENCE is the exact
shape `tests/test_autoclean.py::TestQuarantineArtifactGuard` (NEW-1) had already
ruled insufficient for `_sweep_husks`, the SIBLING reader of the same helper, and
it fails here for the same two repro'd reasons (gate reviewer CRITICAL,
2026-07-27). `_quarantine_registry` RENAMES, so once anything recreates
`state/fleet.json` the file is PRESENT and thin:

  probe D -- a routine spawn recreates fleet.json with one record
  probe F -- an operator "recreates" an EMPTY registry

Either way `_read_registry_readonly` returns `ok`, no record carries the caller's
sid because that record is inside the ARTIFACT, and the §9 arm reads the
thinness as the affirmative *"you are provably not a worker"* it demands. Both
were driven end to end: rc 0, `nonce_seq == 1`, `NONCE:` printed, no `--nonce`
ever passed, artifact still on disk.

SO THERE ARE TWO GATES, AND THEY ARE NOT THE SAME QUESTION:

  gate 1  did the registry ANSWER?      -> `_acting_worker_identity`, absence-aware
  gate 2  was it COMPLETE when it did?  -> the §9 arm, presence-only, `ok` or not

Gate 2 is presence-only *"registry present or not"*, verbatim as `_sweep_husks`
spells it. It does NOT live inside `_acting_worker_identity`: that resolver is
shared with the §6.5 worker-turn gate, which refuses on `True` alone, so
degrading a HEALTHY read to an abstention there would let a real worker turn walk
through §6.5 -- closing the §9 door by opening a wider one. Measured, not
assumed: `TestTheGlobsEdges::test_an_artifact_beside_a_valid_registry_still_
RESOLVES_a_worker` is what goes RED on that change.

`TestTheThreeStepRepro` is the defect itself as a test.
`TestTheRecreatedRegistryBypass` is the CRITICAL -- gate 1 passing, gate 2 catching.
`TestTheFreshInstallCarveOutSurvives` is the test that stops the obvious wrong fix.
`TestTheHelperIsTheONLYSpelling` is the behavioural pin the string-count lint is not.
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


def _roster_run(entries=()):
    """`claude agents --json --all` answering with a roster of our choosing;
    every other argv (i.e. `claude rm`) succeeds silently. Same shape as
    `tests/test_autoclean.py::fake_run_factory`, local so this file does not
    import from another test module."""
    payload = json.dumps(list(entries))

    def run(argv, **kwargs):
        if len(argv) >= 2 and argv[1] == "agents":
            return SimpleNamespace(returncode=0, stdout=payload, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


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
# 1b. THE CRITICAL: absence alone is not the rule -- a RECREATED registry
# --------------------------------------------------------------------------

class TestTheRecreatedRegistryBypass:
    """Keying the rule on registry-file ABSENCE closes step 3 and nothing else.
    `_quarantine_registry` RENAMES, so anything that puts a `state/fleet.json`
    back makes the absence check stop firing while the records the artifact
    holds are still gone. `TestQuarantineArtifactGuard` in
    `tests/test_autoclean.py` had already ruled this out for `_sweep_husks` --
    the sibling reader of the same helper -- naming these same two probes.

    THE CALLER IS A WORKER in both, and that is the escalation: `sid-w1` owns
    the `w1` record, so before the corruption the §6.5 gate refused it outright.
    After the quarantine its record is inside the artifact, the thin registry
    says *"no record carries this sid"*, and the §9 arm reads that as the
    affirmative non-worker verdict it demands -- minting generation 1 for a
    worker, with no `--nonce` ever passed."""

    def _through_step_2(self, monkeypatch):
        """Steps 1 and 2 of the repro, with step 2 driven through the REAL
        `_quarantine_registry` rather than a hand-minted name -- so a change to
        the artifact's spelling breaks these probes instead of silently making
        them test nothing.

        The heartbeat itself never renames (`_acting_worker_identity` reads via
        `_read_registry_readonly`, which is explicitly not `load_registry`); the
        rename is `fleet doctor`'s, which is what makes the repro a SEQUENCE."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        _legacy("sid-w1")
        _corrupt()
        with pytest.raises(fleet.FleetCliError):
            _beat("sid-w1")                              # step 1
        assert fleet.registry_path().exists(), "the read path must never rename"
        fleet._quarantine_registry(fleet.registry_path())          # step 2
        assert not fleet.registry_path().exists()
        assert fleet._quarantine_artifacts()
        with pytest.raises(fleet.FleetCliError):
            _beat("sid-w1")                              # step 3, already closed

    def _assert_refused_and_unminted(self, capsys):
        claim = fleet.read_incarnation()
        assert "nonce_hash" not in claim
        assert "nonce_seq" not in claim
        assert "NONCE:" not in capsys.readouterr().out
        assert fleet._quarantine_artifacts(), "the artifact is still on disk"

    def test_probe_d_a_spawn_recreated_registry_STILL_REFUSES(
            self, qg_home, monkeypatch, capsys):
        """(D) a routine spawn recreates fleet.json with one record."""
        self._through_step_2(monkeypatch)
        _registry({"w2": _rec("sid-w2", status="idle")})   # the spawn
        assert fleet.registry_path().exists()
        # the read SUCCEEDS and answers affirmatively -- gate 1 is satisfied
        assert fleet._acting_body_is_worker_turn(sid="sid-w1") is False
        with pytest.raises(fleet.FleetCliError) as exc:
            _beat("sid-w1")
        assert "restore the quarantined file" in str(exc.value).lower()
        self._assert_refused_and_unminted(capsys)

    def test_probe_f_an_empty_recreated_registry_STILL_REFUSES(
            self, qg_home, monkeypatch, capsys):
        """(F) an operator "recreates" an EMPTY registry."""
        self._through_step_2(monkeypatch)
        _registry({})                                      # the operator
        assert fleet.registry_path().exists()
        assert fleet._acting_body_is_worker_turn(sid="sid-w1") is False
        with pytest.raises(fleet.FleetCliError) as exc:
            _beat("sid-w1")
        assert "restore the quarantined file" in str(exc.value).lower()
        self._assert_refused_and_unminted(capsys)

    def test_restoring_the_RECORD_is_not_enough_while_the_artifact_remains(
            self, qg_home, monkeypatch, capsys):
        """Even a registry rebuilt WITH the worker's own record refuses -- via
        gate 1 this time, because the record makes it a worker turn again. Both
        gates are asserted here so a future refactor cannot silently swap which
        one is load-bearing and call the suite green."""
        self._through_step_2(monkeypatch)
        _registry({"w1": _rec("sid-w1", status="working")})
        assert fleet._acting_body_is_worker_turn(sid="sid-w1") is True
        with pytest.raises(fleet.FleetCliError):
            _beat("sid-w1")
        self._assert_refused_and_unminted(capsys)

    def test_the_refusal_never_advises_recreating_the_registry(
            self, qg_home, monkeypatch):
        """The husk sweep's refusal was made to stop saying "or recreate"
        (`test_refusal_messages_never_advise_recreate`) for exactly this reason:
        recreating is what BOTH probes do. This arm must not reintroduce the
        advice one door over."""
        self._through_step_2(monkeypatch)
        _registry({})
        with pytest.raises(fleet.FleetCliError) as exc:
            _beat("sid-w1")
        assert "recreate" not in str(exc.value).lower()


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
        `_sweep_husks` takes the same presence-only reading, and for the
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

    def test_an_artifact_beside_a_VALID_registry_STILL_REFUSES_the_upgrade(
            self, qg_home, monkeypatch, capsys):
        """THE CRITICAL, in its smallest form. This test previously asserted the
        OPPOSITE -- that a stale artifact must not lock an operator out of the
        §9 upgrade -- on the reasoning that a healthy read is `ok` and answers
        for itself. `ok` is not `complete`: the artifact is precisely the
        evidence that the registry answering may be missing records, because
        `_quarantine_registry` RENAMED them out of it.

        Gate 1 still passes here, and that is the point -- the resolver's
        verdict is unchanged and correct. Gate 2 is what refuses."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _registry({"w1": _rec("sid-w1")})
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        assert fleet.registry_path().exists()
        _legacy("sid-iface")
        # gate 1 is UNCHANGED: the read happened and it was affirmative
        assert fleet._acting_body_is_worker_turn(sid="sid-iface") is False
        with pytest.raises(fleet.FleetCliError) as exc:
            _beat("sid-iface")
        assert ARTIFACT in str(exc.value)
        claim = fleet.read_incarnation()
        assert "nonce_hash" not in claim
        assert "nonce_seq" not in claim
        assert "NONCE:" not in capsys.readouterr().out

    def test_clearing_the_artifact_re_arms_the_upgrade(
            self, qg_home, monkeypatch, capsys):
        """The other direction, and the one that keeps gate 2 from being a
        brick: the remedy the refusal names actually works. Restore the file,
        delete the artifact, and the §9 upgrade is available again -- the same
        re-arming `test_artifact_cleared_and_registry_restored_sweep_resumes`
        pins for the husk sweep."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _registry({"w1": _rec("sid-w1")})
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        _legacy("sid-iface")
        with pytest.raises(fleet.FleetCliError):
            _beat("sid-iface")
        (fleet.state_dir() / ARTIFACT).unlink()
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
        glob pattern exactly once -- inside the helper.

        NOT SUFFICIENT ON ITS OWN, and `TestTheHelperIsTheONLYSpelling` below is
        why: a site that diverges in MEANING while the literal is still spelled
        once passes this count unchanged."""
        src = (fleet.Path(fleet.__file__)).read_text(encoding="utf-8")
        assert src.count('"fleet.json.corrupt.*"') == 1

    def test_it_matches_the_name_the_REAL_writer_mints(self, qg_home):
        """The pattern's `*` is load-bearing and this is what discriminates its
        loss. `_quarantine_registry` appends a timestamp, so a pattern that lost
        the `*` (an exact-name glob) finds nothing while every other test in this
        file, which mints artifact names by hand, could still be satisfied by a
        prefix that happens to match. Driven through the real writer."""
        _registry({"w1": _rec("sid-w1")})
        minted = fleet._quarantine_registry(fleet.registry_path())
        assert minted.name != "fleet.json.corrupt."      # a timestamp was appended
        assert [p.name for p in fleet._quarantine_artifacts()] == [minted.name]

    def test_a_DIRECTORY_artifact_still_counts(self, qg_home):
        """The predicate is presence-of-ANY-ENTRY, not presence-of-a-FILE.

        Pinned because `if p.is_file()` is the natural-looking tightening and it
        was a live hole: injecting it left the whole suite GREEN. It must not be
        added. A quarantine name occupied by a directory is not evidence that
        nothing happened -- it is an unexplained entry sitting exactly where the
        incident record belongs, and every reader of rule 1 refuses on it for the
        same reason it refuses on the file: the state dir is not clean."""
        (fleet.state_dir() / ARTIFACT).mkdir()
        assert [p.name for p in fleet._quarantine_artifacts()] == [ARTIFACT]
        assert fleet._acting_body_is_worker_turn(sid="sid-nobody") is None


# --------------------------------------------------------------------------
# 5. The one-spelling rule, pinned BEHAVIOURALLY rather than by grep
# --------------------------------------------------------------------------

class TestTheHelperIsTheONLYSpelling:
    """`test_the_glob_string_is_written_once_in_the_source` counts a string. A
    site that re-implements the rule with a DIFFERENT meaning -- an inline
    `state_dir().iterdir()` filter, an mtime comparison, an `is_file()` test --
    leaves that count at 1 and passes.

    That is not hypothetical: it is exactly how the wave this file belongs to
    shipped its CRITICAL. Two sites read 'the same' rule, one of them had the
    weaker version, and every lint was green.

    So each reader is pinned by REPLACING the helper and observing that the
    site's behaviour follows. A site that globbed inline would ignore the
    replacement and fail these."""

    def _fake(self, monkeypatch, names):
        monkeypatch.setattr(fleet, "_quarantine_artifacts",
                            lambda: [fleet.state_dir() / n for n in names])

    # -- the §9 arm (gate 2) ------------------------------------------------

    def test_the_S9_arm_refuses_through_the_helper(self, qg_home, monkeypatch):
        """No artifact on disk at all; the helper alone says there is one."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _registry({"w1": _rec("sid-w1")})
        _legacy("sid-iface")
        self._fake(monkeypatch, ["fleet.json.corrupt.SENTINEL"])
        assert not list(fleet.state_dir().glob("fleet.json.corrupt.*"))
        with pytest.raises(fleet.FleetCliError) as exc:
            _beat("sid-iface")
        assert "SENTINEL" in str(exc.value)

    def test_the_S9_arm_GRANTS_when_the_helper_says_clean(
            self, qg_home, monkeypatch, capsys):
        """The discriminating half. A REAL artifact is on disk and the helper is
        silenced: an inline glob at the arm would still refuse."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _registry({"w1": _rec("sid-w1")})
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        _legacy("sid-iface")
        self._fake(monkeypatch, [])
        assert _beat("sid-iface") == 0
        assert "NONCE:" in capsys.readouterr().out

    # -- the husk sweep (I11: previously lint-only) --------------------------

    def test_the_husk_sweep_site_refuses_through_the_helper(self, qg_home, monkeypatch):
        _registry({"w1": _rec("sid-w1")})
        self._fake(monkeypatch, ["fleet.json.corrupt.SENTINEL"])
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet._sweep_husks(False, run=_roster_run(), which=lambda _: "claude")
        assert "SENTINEL" in str(exc.value)

    def test_the_husk_sweep_proceeds_when_the_helper_says_clean(
            self, qg_home, monkeypatch):
        """A REAL artifact on disk, helper silenced. An inline glob at the sweep
        site would refuse and never reach the roster."""
        _registry({"w1": _rec("sid-w1")})
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        self._fake(monkeypatch, [])
        removed, _ = fleet._sweep_husks(False, run=_roster_run(),
                                        which=lambda _: "claude")
        assert removed == []

    # -- the doctor row ------------------------------------------------------

    def test_the_doctor_row_surfaces_through_the_helper(self, qg_home, monkeypatch):
        self._fake(monkeypatch, ["fleet.json.corrupt.SENTINEL"])
        _, _, note = fleet._doctor_check_autoclean(run=_roster_run())
        assert "SENTINEL" in note

    # -- the abstention note (the fifth reader) ------------------------------

    def test_the_abstention_note_reads_through_the_helper(self, qg_home, monkeypatch):
        """`ident` is hand-built rather than resolved, deliberately: the point
        is to isolate THIS site's read of the helper from
        `_acting_worker_identity`'s, which reads it too. A resolved ident would
        make one fake satisfy both and prove neither."""
        self._fake(monkeypatch, ["fleet.json.corrupt.SENTINEL"])
        assert not fleet.registry_path().exists()
        assert "SENTINEL" in fleet._identity_abstention_note({"registry_read": False})

    def test_the_abstention_note_GOES_PLAIN_when_the_helper_says_clean(
            self, qg_home, monkeypatch):
        """The discriminating half: a REAL artifact is on disk and the helper is
        silenced. A site that globbed inline would still name it."""
        (fleet.state_dir() / ARTIFACT).write_text(CORRUPT, encoding="utf-8")
        self._fake(monkeypatch, [])
        assert (fleet._identity_abstention_note({"registry_read": False})
                == "state/fleet.json could not be read")
