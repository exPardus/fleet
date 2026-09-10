"""w63: `sup-status --json` publishes the claim-holder BODY's sid UNION.

THE INCIDENT THIS FILE EXISTS FOR (MEASURED on this host, 2026-09-10). Every
`fleet send` to an idle supervisor FORK-STEERS it: the registry record is
restamped eagerly, `session_id` becomes the fork's sid and the pre-steer sid
moves into `retired_sids`. At 10:38Z the body
`sup|inc-20260910T075355Z-4f99|successor` had TWO live `claude` processes and
TWO rows in `claude agents --json` -- `37e5c61c...` idle at pid 434832 (the
pre-steer session) and `42445477...` busy at pid 515437 (the fork holding the
claim). At 10:16Z, between two turns, only the FIRST of those rows existed, and
the keeper -- which joined the bare claim sid against the roster -- paged
`supervisor-dead` about a supervisor that was alive, listed, and idle.

So the identity a reader must join on is the UNION, and the reason it is
published HERE rather than resolved by each reader is that `sup-status --json`
is where `incarnation.session_id` comes from: resolved in the same call, the
union can never be a fork-steer apart from the sid beside it.
"""
from types import SimpleNamespace

import pytest

import fleet


# The real sids from the 2026-09-10 body, truncated at the point where they
# stop being a measurement and start being a fixture.
CLAIM_SID = "42445477-de98-4813-937a-e18c965de740"
RETIRED_1 = "37e5c61c-cf8f-4fea-9b7b-61f2b22acc60"
RETIRED_2 = "d605e989-91e1-4640-850b-8548e000328f"
BODY = "sup|inc-20260910T075355Z-4f99|successor"


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "supervisor" / "GOALS.md").write_text("# goals\n", encoding="utf-8")
    fleet.save_registry({"workers": {}})
    return tmp_path


def _record(current, retired=()):
    rec = fleet.new_worker_record(current, "/proj", "t", "acceptEdits",
                                  dispatch_kind="bg")
    rec["retired_sids"] = list(retired)
    return rec


def _install(rec, name=BODY):
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)


def _held(sid=CLAIM_SID, **extra):
    claim = {"incarnation_id": "inc-20260910T075355Z-4f99", "session_id": sid,
             "lineage_id": "lin-L", "claimed_via": "handoff",
             "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso()}
    claim.update(extra)
    fleet.write_incarnation(claim)
    return claim


class TestTheUnionResolves:

    def test_the_fork_steered_body_resolves_to_all_three_of_its_sids(self, sup_home):
        """THE MEASURED SHAPE. The claim names the fork; the record carries the
        two sessions it has already been. All three are this one body."""
        _install(_record(CLAIM_SID, [RETIRED_1, RETIRED_2]))
        _held()
        assert fleet.supervisor_claim_sids() == sorted(
            [CLAIM_SID, RETIRED_1, RETIRED_2])

    def test_the_claim_sid_is_always_in_the_result(self, sup_home):
        """A consumer that falls back to the bare sid when this returns None
        must never get a SMALLER answer when it does not."""
        _install(_record(CLAIM_SID, [RETIRED_1]))
        _held()
        assert CLAIM_SID in fleet.supervisor_claim_sids()

    def test_a_stale_claim_sid_still_resolves_through_the_retired_side(self, sup_home):
        """ND4a's window, and the reason the lookup is `_record_sids` and not
        `rec["session_id"] == holder`. `_restamp_after_steer` moves the record
        FORWARD eagerly while `INCARNATION.session_id` restamps only on the
        next validated write, so for one window the claim names a sid that is
        already in `retired_sids`. That body is not unknown; it is the same
        body, and the union is what says so."""
        _install(_record(RETIRED_2, [RETIRED_1, CLAIM_SID]))
        _held(sid=CLAIM_SID)
        assert fleet.supervisor_claim_sids() == sorted(
            [CLAIM_SID, RETIRED_1, RETIRED_2])

    def test_a_body_with_no_registry_record_answers_with_the_bare_sid(self, sup_home):
        """An ANSWER, not a degradation: the registry was readable and no
        record carries this sid, so the one sid we know of is the whole union.
        Distinguished from `None` on purpose -- see the class below."""
        _held()
        assert fleet.supervisor_claim_sids() == [CLAIM_SID]

    def test_another_bodys_record_never_contributes_its_sids(self, sup_home):
        """The union is one record's, never the fleet's. A join that pooled
        every supervisor-shaped record would treat any live supervisor body as
        evidence that THIS one is alive -- which is C2's name-prefix defect
        with extra steps."""
        _install(_record("other-current", ["other-retired"]),
                 name="sup|inc-other|boot")
        _install(_record(CLAIM_SID, [RETIRED_1]))
        _held()
        assert fleet.supervisor_claim_sids() == sorted([CLAIM_SID, RETIRED_1])


class TestTheIndeterminateCasesAreDistinguishable:
    """`None` means "I could not resolve a union", and a caller must be able to
    say so in its output instead of making a claim about a body it could only
    see one session of."""

    def test_no_claim_at_all_is_none(self, sup_home):
        assert fleet.supervisor_claim_sids() is None

    def test_a_released_claim_is_none(self, sup_home):
        _install(_record(CLAIM_SID, [RETIRED_1]))
        fleet.write_incarnation({"incarnation_id": "inc-x", "state": "released",
                                 "session_id": CLAIM_SID,
                                 "released_at": fleet.now_iso()})
        assert fleet.supervisor_claim_sids() is None

    def test_a_claim_with_an_unreadable_holder_sid_is_none(self, sup_home):
        _install(_record(CLAIM_SID, [RETIRED_1]))
        for bad in ({"x": 1}, [], 7, "", None):
            _held(sid=bad)
            assert fleet.supervisor_claim_sids() is None, bad

    def test_a_corrupt_registry_is_none_and_is_not_quarantined(self, sup_home):
        """D4, and the whole reason this reads `_registry_records_or_none`.
        `load_registry` RENAMES a corrupt registry aside, which is a write, and
        `sup-status` is a view. The file must still be there afterwards, under
        its own name, for the operator and for `fleet doctor --repair`."""
        _held()
        reg = fleet.registry_path()
        reg.write_text("{not json", encoding="utf-8")
        assert fleet.supervisor_claim_sids() is None
        assert reg.read_text(encoding="utf-8") == "{not json"
        assert not list(reg.parent.glob("fleet.json.corrupt*"))
        # AND THE DETECTOR CAN SEE A QUARANTINE (the standing rule: a detector
        # that cannot fire proves nothing). `load_registry` -- the thing this
        # function exists NOT to be -- renames the same file on the same input.
        with pytest.raises(Exception):
            fleet.load_registry()
        assert list(reg.parent.glob("fleet.json.corrupt*")), (
            "the glob never matches a real quarantine -- the pin above is vacuous")

    def test_a_corrupt_retired_sids_value_never_raises(self, sup_home):
        """`retired_sids` is read straight out of a file an operator can edit.
        `_record_sids` skips non-str members; a non-list value contributes
        nothing. Either way the union is at worst the bare claim sid, never an
        exception out of a view."""
        for bad in ("not-a-list", {"a": 1}, [None, 7, {"x": 1}, RETIRED_1], None):
            rec = _record(CLAIM_SID)
            rec["retired_sids"] = bad
            _install(rec)
            _held()
            got = fleet.supervisor_claim_sids()
            assert got is not None and CLAIM_SID in got, bad
            assert all(isinstance(s, str) for s in got), bad


class TestTheJsonPublish:

    def test_sup_status_json_carries_the_union(self, sup_home, capsys):
        import json
        _install(_record(CLAIM_SID, [RETIRED_1, RETIRED_2]))
        _held()
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["claim_sids"] == sorted([CLAIM_SID, RETIRED_1, RETIRED_2])
        # ...and it is CONSISTENT with the sid published beside it, which is
        # the entire argument for resolving it here rather than in the keeper.
        assert data["incarnation"]["session_id"] in data["claim_sids"]

    def test_the_union_is_published_outside_the_claim_projection(
            self, sup_home, capsys):
        """§5.8's allowlist governs which CLAIM fields a view may publish. The
        union is a REGISTRY fact about the body, so it must not appear inside
        `incarnation` -- a reader who found it there would reasonably conclude
        `supervisor/INCARNATION` carries it, and it does not."""
        import json
        _install(_record(CLAIM_SID, [RETIRED_1]))
        _held()
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert "claim_sids" in data
        assert "claim_sids" not in data["incarnation"]
        assert "retired_sids" not in data["incarnation"]

    def test_an_unresolvable_union_publishes_null_not_a_guess(
            self, sup_home, capsys):
        import json
        _held()
        fleet.registry_path().write_text("{not json", encoding="utf-8")
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["claim_sids"] is None

    def test_the_human_form_names_the_retired_sids(self, sup_home, capsys):
        """The two-live-body guard is a PROCEDURE A PERSON RUNS, and the
        surface they type by reflex mid-incident is `fleet sup-status`, not
        `--json`. Without this line the operator greps the roster for the one
        sid printed here, does not find it, and concludes the body is gone --
        which is the interface half of the same defect."""
        _install(_record(CLAIM_SID, [RETIRED_1, RETIRED_2]))
        _held()
        assert fleet.cmd_sup_status(SimpleNamespace(json=False)) == 0
        out = capsys.readouterr().out
        assert RETIRED_1 in out and RETIRED_2 in out
        assert "retired sids" in out

    def test_the_human_form_is_unchanged_for_a_body_never_fork_steered(
            self, sup_home, capsys):
        """A line that always prints is a line operators stop reading."""
        _install(_record(CLAIM_SID))
        _held()
        assert fleet.cmd_sup_status(SimpleNamespace(json=False)) == 0
        assert "retired sids" not in capsys.readouterr().out


class TestItIsAViewAndStaysOne:

    def test_the_union_read_never_takes_the_lock(self, sup_home, monkeypatch):
        """CLAUDE.md's standing RULE and terminal-surface D4: a view takes no
        `fleet.lock`. `sup-status` gained a REGISTRY read in w63 and that is
        the one thing about the widening that has to stay true."""
        _install(_record(CLAIM_SID, [RETIRED_1]))
        _held()
        monkeypatch.setattr(fleet, "fleet_lock", lambda *a, **k: pytest.fail(
            "sup-status took fleet.lock"))
        assert fleet.supervisor_claim_sids() is not None
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0

    def test_the_union_read_is_not_load_registry(self, sup_home, monkeypatch):
        """Pinned by BEHAVIOUR, not by reading the source: `load_registry`
        quarantines, so a reader that reached for it would rename a corrupt
        registry aside from a view. `tests/test_load_registry_callers.py` pins
        the scopes; this pins the one function."""
        _install(_record(CLAIM_SID, [RETIRED_1]))
        _held()
        monkeypatch.setattr(fleet, "load_registry", lambda *a, **k: pytest.fail(
            "supervisor_claim_sids reached load_registry"))
        assert fleet.supervisor_claim_sids() == sorted([CLAIM_SID, RETIRED_1])
