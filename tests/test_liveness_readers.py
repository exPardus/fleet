"""w50-live: the three readers of "is this thing alive", made mechanically visible.

THESE TESTS PASS TODAY. Every one of them asserts a CONTRADICTION that is
currently true of shipped code, so a green run here is the receipt that the
disagreement exists -- not that it has been fixed. The build slice described in
`docs/lanes/w50-live.md` §D must INVERT the ones marked `INVERT-ON-BUILD`; a
successor who unifies the readers and leaves this file green has not landed the
change, and that is the point of writing them this way round.

Nothing here requires a production change to run, and nothing here reads the
live fleet: every roster entry below is a literal transcribed from a real
`claude agents --json --all` snapshot taken on win32 2026-08-09 (137 entries),
so the SHAPES are measured even though the fixtures are synthetic.

Floor: stdlib + pytest only, no 3.11+ syntax. Predicted and then measured
identical on py -3.13 and py -3.10.
"""
import ast
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet

FLEET_PY = Path(fleet.__file__).resolve()
SID = "b9b2124d-2c4a-4dde-88b1-c16a992baf8b"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def tree():
    return ast.parse(FLEET_PY.read_text(encoding="utf-8"), filename=str(FLEET_PY))


def _scope_map(tree_):
    """line -> innermost enclosing def/class name."""
    out = {}

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                for ln in range(child.lineno, getattr(child, "end_lineno", child.lineno) + 1):
                    out[ln] = name
                walk(child, name + ".")
            else:
                walk(child, prefix)

    walk(tree_, "")
    return out


def _call_lines(tree_, name):
    return sorted(n.lineno for n in ast.walk(tree_)
                  if isinstance(n, ast.Call)
                  and ((isinstance(n.func, ast.Name) and n.func.id == name)
                       or (isinstance(n.func, ast.Attribute) and n.func.attr == name)))


def _key_write_lines(tree_, key):
    """Every site that STORES `key`: `d[key] = v` and `{key: v}` alike.

    The second class is why this helper exists. The first version of this
    census used `ast.Subscript` only and reported 5 heartbeat writers when
    there are 8 -- a dict LITERAL is an `ast.Dict`, not a `Subscript`. The
    control in `test_the_heartbeat_census_has_no_hole` is what caught it.
    """
    out = []
    for node in ast.walk(tree_):
        if isinstance(node, ast.Dict):
            out += [k.lineno for k in node.keys
                    if isinstance(k, ast.Constant) and k.value == key]
        elif isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and sl.value == key \
                    and isinstance(node.ctx, ast.Store):
                out.append(node.lineno)
    return sorted(set(out))


def _iso(dt):
    """fleet's registry timestamp format. NOT `datetime.isoformat()` --
    `_parse_iso` is a bare `strptime("%Y-%m-%dT%H:%M:%SZ")` and raises on the
    offset form, which `_launch_claim_expired` swallows into "not expired".
    The first draft of this file used `.isoformat()` and every recompute test
    passed through the DISPATCH GRACE branch instead of the branch it named --
    green for the wrong reason, which is the failure mode this lane is about."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _native_record(**over):
    """A minimal dispatch_kind:"bg" record past its dispatch grace window, so
    no branch below resolves through `_dispatch_grace_active` by accident."""
    old = _iso(datetime.now(timezone.utc) - timedelta(hours=6))
    rec = {"dispatch_kind": "bg", "session_id": SID, "status": "working",
           "created": old, "last_dispatch_at": old, "last_activity": old,
           "cwd": ".", "task": "t", "mode": "bypass", "turns": 1,
           "cost_usd": 0.0, "retired_sids": []}
    rec.update(over)
    return rec


def _grace_is_shut(rec):
    """Guard against the vacuous green described in `_iso`: assert the record
    really is past its grace window, so a `working` verdict below can only
    have come from the roster branch under test."""
    return fleet._dispatch_grace_active(rec) is False


# ---------------------------------------------------------------------------
# Fixtures for the DRIVEN tests in TestWhatACanonicalAnswerMustPreserve.
# These drive real verbs, so they need a real home shape -- the module's
# `isolated_home` only repoints FLEET_HOME.
# ---------------------------------------------------------------------------

_CARRIER = "sup|inc-old|boot"
_RELEASER = "sid-releaser-0000"
# A record the releasing body already HAD is necessarily older than the release
# it performed -- the fork-steer boundary `_releaser_live_sids` draws.
_BEFORE_RELEASE = "2020-01-01T00:00:00Z"


class _ReachedDispatch(Exception):
    """Sentinel: control flow got PAST the roster gate and would have launched
    a real session. Raised instead of dispatching, so a control can assert
    "this proceeded" without a claude process ever existing."""


def _must_not_dispatch(*_a, **_k):
    raise _ReachedDispatch()


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """A home complete enough for `respawn`, `clean` and `sup-*` to run."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir(exist_ok=True)
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    (tmp_path / "supervisor" / "GOALS.md").write_text(
        "# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge" / "INDEX.md").write_text(
        "# Knowledge Index\n- entry one\n", encoding="utf-8")
    fleet.save_registry({"workers": {}})
    return tmp_path


def _install_worker(home, name="w", sid=SID):
    rec = fleet.new_worker_record(sid, str(home / "proj"), "task", "bypass",
                                  dispatch_kind="bg")
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    (home / "proj").mkdir(exist_ok=True)
    return rec


def _install_release_carrier(home, archived=False):
    """A record carrying a RELEASED claim's `released_by_sid`, produced by the
    shipped verbs rather than hand-planted: hold a claim, then `sup-release`."""
    rec = fleet.new_worker_record(_RELEASER, str(home / "proj"), "t", "bypass",
                                  dispatch_kind="bg")
    rec["created"] = _BEFORE_RELEASE
    if archived:
        rec["archived_at"] = fleet.now_iso()
    data = fleet.load_registry()
    data["workers"][_CARRIER] = rec
    fleet.save_registry(data)

    value = fleet.mint_nonce()
    beat = fleet.now_iso()
    fleet.write_incarnation(
        {"incarnation_id": "inc-old", "session_id": _RELEASER,
         "claimed_at": beat, "heartbeat_at": beat, "claimed_via": "fresh",
         "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 1,
         "lineage_id": "lin-20260101T000000Z-aaaa"})
    assert fleet.cmd_sup_release(
        SimpleNamespace(sid=_RELEASER, nonce=value, reason=None)) == 0
    return rec


def _write_claim(age_seconds):
    """A HELD, non-legacy claim owned by a body that is not the caller.

    Non-legacy matters: `_claim_is_legacy` is "`nonce_hash` absent AND `state`
    absent", and a legacy claim disarms the gate for a different reason
    (§9, no generation to demand). Carrying a `nonce_hash` keeps the staleness
    branch the only thing that can disarm it."""
    beat = _iso(datetime.now(timezone.utc) - timedelta(seconds=age_seconds))
    fleet.write_incarnation(
        {"incarnation_id": "inc-held", "session_id": "the-holder-body",
         "claimed_at": beat, "heartbeat_at": beat, "claimed_via": "fresh",
         "state": "held", "nonce_hash": fleet.nonce_digest(fleet.mint_nonce()),
         "nonce_seq": 1, "lineage_id": "lin-20260101T000000Z-bbbb"})


# ---------------------------------------------------------------------------
# THE CENSUS, as pins. A census is a claim about a count; a claim about a
# count that nothing re-derives is the defect this repo is named for.
# ---------------------------------------------------------------------------

class TestTheCensus:
    def test_roster_live_sids_call_sites_are_this_exact_POPULATION(self, tree):
        """The brief said 10, counted by grep. Grep sees 14 lines: 11 calls,
        1 def, 2 docstring mentions. The AST cannot see the last three.

        THIS PINS THE POPULATION, NOT THE COUNT, and the difference is a
        measured mutant. The first version asserted `len(calls) == 11` and
        failed with `f"call sites moved: {calls}"` -- naming the very thing it
        could not detect. The w50 gate defeated it with a two-part patch:

            # part 1 -- site 10 stops consulting Q1 at all
            -    live_now = _releaser_live_sids(claim, _roster_live_sids(payload),
            +    live_now = _releaser_live_sids(claim, _mutant_d_decoy(payload),
            # part 2 -- a compensating call elsewhere, so the count is unchanged
            +def _mutant_d_decoy(entries):
            +    return _roster_live_sids(entries)

        Eleven calls before, eleven after, and `_wedged_release_gate` -- the
        one site the report calls "the trap" -- no longer reads Q1. A count
        assertion is defeated by ANY same-arity rearrangement; a scope
        multiset is not. Same shape as
        `test_the_heartbeat_census_has_no_hole`, which asserts scopes."""
        smap = _scope_map(tree)
        calls = _call_lines(tree, "_roster_live_sids")
        got = Counter(smap.get(ln, "<module>") for ln in calls)
        expected = Counter({
            "_cmd_respawn_native": 3,
            "_cmd_respawn_supervisor": 1,
            "_cmd_respawn_supervisor._any_live": 1,
            "cmd_clean": 1,
            "_archive_eligible": 1,
            "_render_boot_bundle": 1,
            "cmd_sup_boot": 1,
            "_wedged_release_gate": 1,
            "_doctor_check_supervisor_wedge": 1,
        })
        assert got == expected, (
            f"the Q1 call-site POPULATION moved.\n"
            f"  gained: {got - expected}\n  lost:   {expected - got}\n"
            f"A site that disappears from this map has stopped reading Q1 even "
            f"if the total is unchanged -- which is exactly the mutant this "
            f"assertion exists to catch.")
        assert sum(expected.values()) == 11

        # COUNT CONTROL, both limbs. A census whose good answer might be zero
        # must be shown to be able to report non-zero AND zero (wave 38).
        assert _call_lines(tree, "zzz_definitely_not_a_function") == []
        assert len(_call_lines(tree, "_fetch_agents_roster")) > 0

        # SHAPE CONTROL (wave 42): the thing a grep census miscounts is a
        # mention inside a string. Prove such mentions EXIST, or the control
        # passes vacuously against data that never had the hazard.
        in_strings = sum(1 for n in ast.walk(tree)
                         if isinstance(n, ast.Constant)
                         and isinstance(n.value, str)
                         and "_roster_live_sids" in n.value)
        assert in_strings >= 1, "no string mentions -- control cannot discriminate"
        raw = sum(1 for line in FLEET_PY.read_text(encoding="utf-8").splitlines()
                  if "_roster_live_sids" in line)
        assert raw > len(calls), (
            f"textual count {raw} must exceed AST call count {len(calls)}; "
            f"if they are equal the AST census has stopped discriminating")

    def test_every_reader_named_in_the_brief_still_exists(self, tree):
        """A census over names that have been renamed is a census over
        nothing. Four mutants survived a full suite in wave 35 this way."""
        names = ["_roster_live_sids", "_releaser_live_sids",
                 "_releaser_is_roster_live", "recompute_worker_native",
                 "native_epoch_suspicious", "supervisor_epoch_check",
                 "_roster_entry_has_life_signal", "_investigate_no_outcome",
                 "_supervisor_tier_snapshot", "_dispatch_grace_active",
                 # Added by the w50 gate (F5): the REGISTRY-side liveness
                 # predicate. Its absence from this list is how the census
                 # asserted a closed population by omission.
                 "_record_is_live"]
        defined = {n.name for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert not [n for n in names if n not in defined]

    def test_the_reader_population_is_not_asserted_closed(self, tree):
        """The honest pin: this file does NOT claim to have found every
        liveness reader, and must not be read as claiming it.

        What it CAN pin is that the readers it names still exist and that any
        function whose name advertises a liveness question is either in the
        census or deliberately excluded. A name-shaped sweep is weaker than a
        semantic one and is labelled as such -- `_dispatch_grace_active` is a
        liveness reader whose name contains none of these tokens, which is
        precisely why the sweep cannot be the closure argument."""
        censused = {
            "_roster_live_sids", "_releaser_live_sids", "_releaser_is_roster_live",
            "_roster_entry_has_life_signal", "_record_is_live",
            "recompute_worker_native", "native_epoch_suspicious",
            "supervisor_epoch_check", "_investigate_no_outcome",
            "_supervisor_tier_snapshot", "_dispatch_grace_active",
            # nested in `_cmd_respawn_supervisor`; it IS a Q1 reader and the
            # call-site map above already carries it as
            # `_cmd_respawn_supervisor._any_live`
            "_any_live",
        }
        excluded = {
            # roster PLUMBING, not a liveness verdict
            "_fetch_agents_roster", "_roster_entry_for",
            # claim/identity predicates that consume a liveness answer rather
            # than producing one
            "_releaser_body_is_tombstoned", "_claim_resume_allowed",
            "_await_attach", "_join_roster_by_short_id",
            # A NAME-SHAPED FALSE POSITIVE, and a useful one to keep listed:
            # "live" here means "does this machine have a live POPULATION of
            # fleet homes", i.e. multi-fleet territory. Nothing to do with a
            # session or a process. Its own docstring: "Is this machine in
            # multi-fleet territory at all?" This is the evidence that the
            # sweep is a heuristic and cannot be the closure argument.
            "_multi_fleet_population_is_live",
        }
        shaped = {n.name for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and any(tok in n.name for tok in ("_live", "live_", "alive",
                                                    "_roster", "roster_"))}
        unaccounted = shaped - censused - excluded
        assert not unaccounted, (
            f"a liveness-shaped name is in neither the census nor the "
            f"exclusion list: {sorted(unaccounted)}. Add it to one -- the w50 "
            f"gate found `_record_is_live` exactly here.")
        # CONTROL: the sweep must actually be finding things, or an empty
        # `shaped` set would satisfy it vacuously.
        assert len(shaped) >= 6, f"sweep found only {sorted(shaped)}"

    def test_the_heartbeat_census_has_no_hole(self, tree):
        """MEASURED: 8 write sites, all inside a `sup-*` verb's function.

        The control is the reconciliation, not the count: every textual
        occurrence of the key must be accounted for as a classified AST node
        or as a comment/docstring line. An unclassified remainder means the
        census has a blind spot -- which is exactly how this test's own helper
        was found to be missing `ast.Dict` keys."""
        writes = _key_write_lines(tree, "heartbeat_at")
        smap = _scope_map(tree)
        scopes = sorted({smap.get(ln, "<module>") for ln in writes})
        assert len(writes) == 8, f"heartbeat writers moved: {writes}"
        assert all(s.startswith("cmd_sup_") or s.startswith("_cmd_sup_")
                   for s in scopes), scopes

        # CONTROL: reconcile against the raw text. Anything the AST did not
        # classify must be a comment or a docstring, never code.
        src = FLEET_PY.read_text(encoding="utf-8").splitlines()
        textual = [i + 1 for i, line in enumerate(src) if "heartbeat_at" in line]
        reads = sorted({n.lineno for n in ast.walk(tree)
                        if isinstance(n, ast.Subscript)
                        and isinstance(n.slice, ast.Constant)
                        and n.slice.value == "heartbeat_at"})
        unclassified = [ln for ln in textual if ln not in set(writes) | set(reads)]

        # "Prose" means INSIDE a string node's span or on a comment line --
        # not "the line happens to contain a quote". A multi-line docstring's
        # interior lines carry no quote at all, which is how the first draft
        # of this control produced a false hole at :14994.
        prose = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for ln in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1):
                    prose.add(ln)
        for ln in unclassified:
            body = src[ln - 1].strip()
            assert ln in prose or body.startswith("#"), (
                f"line {ln} mentions heartbeat_at but is neither a classified "
                f"AST node, a comment, nor inside a string: {body!r} -- the "
                f"census has a hole")
        # CONTROL on the control: it must have had something to classify, or
        # a census that silently found nothing would also pass.
        assert len(unclassified) >= 5, (
            f"expected prose mentions to reconcile, got {unclassified}")


# ---------------------------------------------------------------------------
# DISAGREEMENT 1 -- `respawn` says LIVE, `status` says IDLE, same entry, same
# instant. The brief blamed the Windows `done` parenthetical. It is not that.
# ---------------------------------------------------------------------------

class TestDisagreementOne:
    # Transcribed from the live roster, 2026-08-09: an earlier supervisor
    # incarnation, alive as a process, its turn over.
    LIVE_SHAPE = {"sessionId": SID, "state": "blocked", "status": "idle",
                  "pid": 38336, "kind": "bg", "name": "sup|inc-c477|boot",
                  "cwd": "C:/proga/claude-fleet", "startedAt": "2026-08-09T01:49:12Z"}

    def test_respawn_and_status_split_on_a_real_roster_entry(self, monkeypatch):
        """INVERT-ON-BUILD. One entry, two readers, opposite answers.

        `_roster_live_sids` asks "does a process exist" and never looks at
        `status`'s VALUE. `recompute_worker_native` decides on exactly that
        value. Neither is wrong about its own question; they are being read
        as answers to one question."""
        entries = [self.LIVE_SHAPE]
        monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)

        # Reader A -- the one `fleet respawn` gates on (bin/fleet.py:8230).
        assert SID in fleet._roster_live_sids(entries), \
            "reader A must call this entry LIVE (keys present, state != done)"

        # Reader B -- the one `fleet status` renders (bin/fleet.py:3760).
        verdict = fleet.recompute_worker_native("w", _native_record(), entries)
        assert verdict["status"] == "idle", \
            "reader B must call the same entry IDLE"

        # The contradiction, stated as the operator experiences it: respawn
        # refuses ("turn is running") a worker the status table calls idle.
        assert (SID in fleet._roster_live_sids(entries)) != (verdict["status"] == "working")

    def test_the_split_survives_removing_the_done_clause_entirely(self, monkeypatch):
        """The brief's causal claim, falsified. If the `state != "done"`
        clause were the cause, an entry that is not `done` could not split
        the readers. This one is `blocked`, and it splits them anyway."""
        assert self.LIVE_SHAPE["state"] != "done"
        monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)
        assert SID in fleet._roster_live_sids([self.LIVE_SHAPE])
        assert fleet.recompute_worker_native(
            "w", _native_record(), [self.LIVE_SHAPE])["status"] == "idle"

    def test_recompute_has_a_third_inline_spelling_with_no_done_clause(self, monkeypatch):
        """INVERT-ON-BUILD. A LATENT divergence, and the sharper one.

        `recompute_worker_native:3760` re-spells the roster-liveness predicate
        inline as key-presence ALONE -- the `state != "done"` guard that
        `_roster_live_sids` calls load-bearing is simply absent.

        CORRECTED after the w50 gate (F1). This docstring used to say the
        exact shape below had "ZERO instances" on win32 and was "unreachable
        there today", reachable only on posix. That was wrong, and it was
        wrong because one snapshot taken by a busy session was generalised
        into a property of the platform. Re-measured with a detached sampler:
        `{state:"done"}` WITH keys is routine on win32 -- three concurrent
        instances. `status:"busy"` alongside it was still not observed, so
        THIS entry's exact triple remains synthetic; what is no longer
        synthetic is its enabling condition."""
        entry = {"sessionId": SID, "state": "done", "status": "busy", "pid": 4321}
        monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: False)
        rec = _native_record()
        assert _grace_is_shut(rec), (
            "this test is only meaningful with the grace window CLOSED -- "
            "otherwise `working` comes from `_investigate_no_outcome`, not "
            "from the roster branch under test")

        assert fleet._roster_live_sids([entry]) == set(), \
            "reader A: terminal state dominates key presence -- NOT live"
        assert fleet.recompute_worker_native(
            "w", rec, [entry])["status"] == "working", \
            "reader B: key presence alone, then status=='busy' -- WORKING"

        # And the proof that `busy` is what carried it: flip the roster status
        # to `idle` and the same record with the same closed grace window
        # lands on `dead-suspected` instead.
        idle_entry = dict(entry, status="idle")
        assert fleet.recompute_worker_native(
            "w", rec, [idle_entry])["status"] == "dead-suspected"


class TestTheShapeABusySessionActuallyPresents:
    """W50 GATE F1, and then one step past it.

    The gate falsified the report's "zero done-with-keys on win32" with n=1 --
    the lane's own session, between turns. Re-measuring with a detached
    sampler (29 samples, 20s apart, ~10 minutes, from a process outside every
    session it observed) found **three** distinct sids in that shape
    simultaneously, and one of them was the lane's own session **while it was
    executing a turn**:

        state="done"  status="idle"  pid=4436  alive=True   x29/29 samples

    The turn was running for the whole window -- the sampler was launched from
    inside it. So on win32, today, the roster's `state` and `status` can both
    be wrong about a session that is actively working, while key-presence and
    the OS are right. That is MEASURED. WHY is not: the mechanism is most
    likely that `state` flips to `done` at turn end and is not flipped back
    when a subsequent turn begins in the same session, but this lane could not
    observe its own turn boundary from inside, and no session it was permitted
    to drive would have shown the other direction. Stated as BELIEVED in
    `docs/lanes/w50-live.md` §3.

    The consequence does not depend on the mechanism, and it is the direction
    that matters: `_roster_live_sids` excludes this entry, so `fleet respawn`
    does NOT refuse -- the false-DEAD branch, on a session that is mid-turn.
    """

    BUSY_BUT_DONE = {"sessionId": SID, "state": "done", "status": "idle",
                     "pid": 4436, "kind": "background",
                     "cwd": "C:\\proga\\fleet-w50-live"}

    def test_the_q1_predicate_calls_a_working_session_not_live(self):
        """INVERT-ON-BUILD. The terminal-state rule dominates key presence --
        correct for a lingering finished session (the 2026-07-19 macOS
        finding), and wrong for this one, which is the same shape."""
        assert fleet._roster_live_sids([self.BUSY_BUT_DONE]) == set()

    def test_and_therefore_respawn_would_not_refuse_it(
            self, sup_home, monkeypatch):
        """The hazard, driven rather than argued. `respawn` refuses only when
        the old sid is in the Q1 live set; this shape is not, so it proceeds
        to stop a session whose OS process is alive and mid-turn.

        Contrast `test_respawn_refuses_on_an_unfetchable_roster_even_with_force`:
        respawn is scrupulously conservative about an UNKNOWN roster and has no
        defence at all against a roster that is confidently WRONG."""
        _install_worker(sup_home)
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [self.BUSY_BUT_DONE]))
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        monkeypatch.setattr(fleet, "_stop_native_session", lambda *a, **k: True)
        monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)

        with pytest.raises(_ReachedDispatch):
            fleet.cmd_respawn(SimpleNamespace(
                name="w", task=None, force=False, yes=True, nonce=None,
                max_budget_usd=None, setting_sources=None, token_ceiling=None))

    def test_control_it_DOES_refuse_the_same_session_shown_as_working(
            self, sup_home, monkeypatch):
        """The control that makes the test above mean something: flip only
        `state`/`status` to the mid-turn shape and the identical call refuses.
        The difference between stopping a working session and refusing to is
        two string fields the roster got wrong."""
        _install_worker(sup_home)
        working = dict(self.BUSY_BUT_DONE, state="working", status="busy")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [working]))
        monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)

        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_respawn(SimpleNamespace(
                name="w", task=None, force=False, yes=True, nonce=None,
                max_budget_usd=None, setting_sources=None, token_ceiling=None))
        assert "turn is running" in str(ei.value)


class TestTheWindowsParenthetical:
    """`(On Windows the two conditions agree -- done entries lose pid/status.)`

    The sentence is a BICONDITIONAL and BOTH directions are false on win32.
    Re-measured after the w50 gate falsified this class's first version.

      * forward  (`done` => no keys): **FALSE**, 3 concurrent counter-examples
        in a 29-sample detached run, one of them a session that was executing
        a turn at the time.
      * reverse  (no keys => `done`): **FALSE**, 60 counter-examples in the
        same population -- `blocked` x32, `stopped` x26, `failed` x2.

    The first version of this class asserted the forward direction HELD and
    that the clause was therefore inert here. Both fixtures below now carry
    measured shapes for both directions."""

    KEYLESS_NOT_DONE = [
        {"sessionId": "s-blocked", "state": "blocked"},   # 32 live instances
        {"sessionId": "s-stopped", "state": "stopped"},   # 26 live instances
        {"sessionId": "s-failed", "state": "failed"},     # 2 live instances
    ]
    # MEASURED, and this is the fixture the previous version of this file did
    # not have: `done` WITH keys, three of them live simultaneously.
    DONE_WITH_KEYS = [
        {"sessionId": "s-done-1", "state": "done", "status": "idle", "pid": 4436},
        {"sessionId": "s-done-2", "state": "done", "status": "idle", "pid": 41464},
        {"sessionId": "s-done-3", "state": "done", "status": "idle", "pid": 38740},
    ]

    def test_the_reverse_direction_of_the_biconditional_is_false(self):
        for entry in self.KEYLESS_NOT_DONE:
            assert entry["state"] != "done"
            assert "pid" not in entry and "status" not in entry
            assert fleet._roster_live_sids([entry]) == set(), (
                "not-done and yet not live: the two conditions do NOT agree")

    def test_the_forward_direction_is_false_too(self):
        """What the gate found, as a fixture. `done` entries do NOT lose
        pid/status on win32."""
        for entry in self.DONE_WITH_KEYS:
            assert entry["state"] == "done"
            assert "pid" in entry and "status" in entry

    def test_the_done_clause_is_NOT_inert_and_changes_exactly_these_answers(self):
        """REPLACES `test_the_done_clause_is_inert_on_a_windows_shaped_roster`,
        which asserted the opposite and was measured wrong.

        On a roster of the shape win32 actually presents, dropping the clause
        changes the verdict for every `done`-with-keys entry -- and each of
        those is the difference between `fleet respawn` refusing and
        proceeding against a live OS process."""
        roster = self.KEYLESS_NOT_DONE + self.DONE_WITH_KEYS + [
            {"sessionId": "s-done-reaped", "state": "done"},
            {"sessionId": "s-live", "state": "working", "status": "busy", "pid": 7},
        ]
        with_clause = fleet._roster_live_sids(roster)
        without_clause = {e["sessionId"] for e in roster
                          if "status" in e or "pid" in e}
        assert with_clause == {"s-live"}
        assert without_clause - with_clause == {"s-done-1", "s-done-2", "s-done-3"}
        assert with_clause != without_clause, "the clause is NOT inert"


# ---------------------------------------------------------------------------
# THE FOURTH READER -- not named in the brief. It answers the OPPOSITE way on
# 131 of the 139 entries measured, not the 60 above: the `done` bucket (71)
# disagrees too, and the report's first draft counted only the reverse-
# counter-example population. The loop below has always iterated `done`, so
# the TEST asserted the wider property while the PROSE narrowed it (gate F9).
# ---------------------------------------------------------------------------

class TestTheReaderTheBriefDidNotName:
    def test_life_signal_and_roster_live_are_exact_opposites_here(self):
        """INVERT-ON-BUILD. `_roster_entry_has_life_signal` counts a
        terminal `state` as PROOF OF LIFE; `_roster_live_sids` counts the
        same entry as dead. Both shipped, 40 lines apart in purpose.

        They are not contradicting each other by accident: one asks "did this
        session ever attach" (handoff identity proof) and the other asks "is a
        process running now" (respawn safety). Same word, two questions."""
        for state in ("done", "failed", "stopped", "blocked"):
            entry = {"sessionId": "x", "state": state}
            assert fleet._roster_entry_has_life_signal(entry) is True
            assert fleet._roster_live_sids([entry]) == set()

    def test_they_agree_only_where_the_keys_are_present(self):
        entry = {"sessionId": "x", "state": "working", "status": "busy", "pid": 1}
        assert fleet._roster_entry_has_life_signal(entry) is True
        assert fleet._roster_live_sids([entry]) == {"x"}


class TestTheThirteenthReader:
    """`_record_is_live` (`bin/fleet.py:2993`), found by the w50 gate (F5).

    It answers Q1 from the REGISTRY rather than the roster, and the census
    never opened it. It matters to the ruling specifically: it reaches
    `_wedged_release_gate` -- the site the report calls "the trap" -- through
    `_releaser_live_sids`'s tombstone arm, and §6.2's proposed predicate takes
    roster arguments only, with no registry argument and therefore no place for
    this reader. Build §6 as first specified and a fourth spelling of Q1
    survives the consolidation, inside the one gate the report warns about."""

    def test_it_calls_live_the_very_record_recompute_just_called_dead(
            self, monkeypatch):
        """INVERT-ON-BUILD. `recompute_worker_native` demotes a record to
        `dead-suspected` precisely because it could find no life for it;
        `_record_is_live` reads that same record and returns True."""
        monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: False)
        monkeypatch.setattr(fleet, "_limit_scan_hook", None)
        rec = _native_record()
        assert _grace_is_shut(rec)

        demoted = fleet.recompute_worker_native("w", rec, [])   # roster-GONE
        assert demoted["status"] == "dead-suspected"
        assert fleet._record_is_live(demoted) is True, (
            "the registry-side reader must be shown disagreeing with the "
            "roster-side one on the SAME record")

    def test_only_an_explicit_dead_or_an_archive_stops_it(self):
        """Its whole predicate is `not archived and status != "dead"`, so every
        other terminal-ish status reads as live -- including `limited`,
        `stopped`, `failed` and `dead-suspected`."""
        for status in ("working", "idle", "dead-suspected", "stopped",
                       "failed", "limited", "blocked"):
            assert fleet._record_is_live({"status": status}) is True, status
        # CONTROL, both limbs -- a predicate that always returned True would
        # satisfy the loop above.
        assert fleet._record_is_live({"status": "dead"}) is False
        assert fleet._record_is_live(
            {"status": "idle", "archived_at": "2026-01-01T00:00:00Z"}) is False
        assert fleet._record_is_live("not-a-dict") is False

    def test_the_husk_that_reached_234h_is_live_to_this_reader_throughout(self):
        """Why it lands on §5.3's argument. The five `dead-suspected` husks
        that accumulated to 234h -- the report's own example of a signal
        nobody is obliged to act on -- are `live` to this reader for every one
        of those hours, because `dead-suspected` is not `dead`."""
        husk = {"status": "dead-suspected", "session_id": SID,
                "dispatch_kind": "bg"}
        assert fleet._record_is_live(husk) is True


# ---------------------------------------------------------------------------
# DISAGREEMENT 2 -- the supervisor waited on a lane that was already done.
# ---------------------------------------------------------------------------

class TestDisagreementTwo:
    def test_an_epoch_freeze_holds_a_finished_worker_pending_forever(
            self, isolated_home, monkeypatch):
        """INVERT-ON-BUILD (partly -- see the ruling; this one may be
        correct as designed and want a SURFACE, not a fix).

        `native_epoch_suspicious` freezes every native verdict when the
        roster fetch fails. `wait_for_workers` then `continue`s past the
        worker without recomputing, so a lane whose OWN recompute says
        `idle` stays `pending` until the wait times out. The supervisor's
        wall-clock is the cost, and no message anywhere says a freeze
        happened."""
        rec = _native_record(status="working")
        fleet.save_registry({"workers": {"lane": rec}})

        finished_entry = [{"sessionId": SID, "state": "done"}]
        monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)

        # Ground truth: the worker's own recompute says it is done.
        assert fleet.recompute_worker_native(
            "lane", rec, finished_entry)["status"] == "idle"

        # CONTROL FIRST -- the harness must be able to report "finished" at
        # all, or the frozen run below proves nothing (wave 38: a measurement
        # whose good answer is zero, run only against the zero case).
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda *a, **k: (True, finished_entry))
        fin, pend = fleet.wait_for_workers(
            ["lane"], mode="all", timeout=0, sleep=lambda s: None,
            clock=_fake_clock())
        assert fin == {"lane": "idle"} and pend == set(), \
            "CONTROL FAILED: the harness cannot resolve a finished worker at all"

        # Now the freeze: same worker, same roster content, fetch reports
        # failure. The verdict is not merely delayed -- it is never computed.
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda *a, **k: (False, "transient CLI failure"))
        fin, pend = fleet.wait_for_workers(
            ["lane"], mode="all", timeout=0, sleep=lambda s: None,
            clock=_fake_clock())
        assert fin == {} and pend == {"lane"}, \
            "the epoch freeze must hold the finished lane pending"

    def test_the_freeze_also_fires_on_a_merely_empty_roster(self, isolated_home):
        """The shape that makes this bite in practice: `claude agents` exits 0
        with `[]`. `roster_ok` is True, so nothing looks broken, and every
        record whose last-committed status is `working` freezes."""
        workers = {"lane": _native_record(status="working")}
        assert fleet.native_epoch_suspicious(True, [], workers) is True
        # CONTROL, the zero limb: with a non-empty roster it must NOT freeze.
        assert fleet.native_epoch_suspicious(
            True, [{"sessionId": SID, "state": "done"}], workers) is False
        # CONTROL, the shape limb: an empty roster with no `working` record is
        # also not suspicious -- so the predicate is reading the registry, not
        # merely the roster's emptiness.
        assert fleet.native_epoch_suspicious(
            True, [], {"lane": _native_record(status="idle")}) is False


def _fake_clock():
    """Monotonic clock that is already past any deadline, so `wait_for_workers`
    runs exactly one poll and returns. Deterministic on both floors -- no
    wall-time, no sleep."""
    ticks = iter([0.0] + [10_000.0] * 64)

    def clock():
        try:
            return next(ticks)
        except StopIteration:
            return 10_000.0

    return clock


# ---------------------------------------------------------------------------
# DISAGREEMENT 3 -- a watcher called a live, mid-merge supervisor dead.
# ---------------------------------------------------------------------------

class TestDisagreementThree:
    def _claim(self, home, age_seconds):
        beat = _iso(datetime.now(timezone.utc) - timedelta(seconds=age_seconds))
        path = fleet.supervisor_dir() / "INCARNATION"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "incarnation_id": "inc-test", "session_id": SID,
            "claimed_at": beat, "heartbeat_at": beat, "claimed_via": "sup-boot",
            "state": "held"}), encoding="utf-8")
        return path

    def test_no_reader_in_the_tree_ever_converts_beat_age_into_deadness(
            self, isolated_home):
        """MEASURED, and it is the whole finding: the code never says the
        supervisor is dead. `_supervisor_tier_snapshot` reports `held` and an
        AGE, at any staleness. The watcher supplied the inference."""
        self._claim(isolated_home, 40 * 60)          # 40 minutes of merge work
        snap = fleet._supervisor_tier_snapshot()
        assert snap["state"] == "held"
        assert snap["heartbeat_age_seconds"] > 2000

        self._claim(isolated_home, 400 * 60 * 60)    # absurdly stale
        snap = fleet._supervisor_tier_snapshot()
        assert snap["state"] == "held", \
            "no staleness converts the claim state to anything but `held`"

    def test_the_snapshot_carries_no_process_liveness_field_at_all(
            self, isolated_home):
        """INVERT-ON-BUILD. The projection a watcher reads has four keys and
        none of them is about a process. There is nothing here for a correct
        watcher to key on, which is why it keyed on the beat."""
        self._claim(isolated_home, 60)
        snap = fleet._supervisor_tier_snapshot()
        assert set(snap) == {"goals_active", "state", "incarnation_id",
                             "heartbeat_age_seconds"}
        assert not [k for k in snap if "pid" in k or "live" in k or "alive" in k]

    def test_a_busy_supervisor_and_a_dead_one_are_the_same_snapshot(
            self, isolated_home):
        """The defect, as one assertion. Two supervisors, one merging for
        forty minutes and one whose host process died forty minutes ago,
        produce byte-identical projections."""
        self._claim(isolated_home, 40 * 60)
        busy = fleet._supervisor_tier_snapshot()
        self._claim(isolated_home, 40 * 60)
        dead = fleet._supervisor_tier_snapshot()
        busy.pop("heartbeat_age_seconds")
        dead.pop("heartbeat_age_seconds")
        assert busy == dead

    def test_the_gate_disarms_on_the_same_staleness_the_watcher_read_as_death(
            self, isolated_home):
        """Cost asymmetry, opposite sign. The watcher's false-dead cost the
        interface a wasted intervention. The SAME stale beat silently DISARMS
        `_supervisor_gate`, so `fleet clean --yes` from a third body stops
        being refused -- and nothing prints."""
        assert fleet.SUPERVISOR_CLAIM_STALE_SECONDS > 0
        fresh = {"state": "held", "session_id": SID, "incarnation_id": "i",
                 "heartbeat_at": _iso(datetime.now(timezone.utc))}
        stale_at = (datetime.now(timezone.utc)
                    - timedelta(seconds=fleet.SUPERVISOR_CLAIM_STALE_SECONDS + 60))
        stale = dict(fresh, heartbeat_at=_iso(stale_at))
        # Read the age the gate reads, rather than driving the gate (which
        # needs a nonce, a registry and a verb): the disarm is a pure
        # comparison and this is the comparison.
        now = datetime.now(timezone.utc)
        fresh_age = (now - fleet._parse_iso(fresh["heartbeat_at"])).total_seconds()
        stale_age = (now - fleet._parse_iso(stale["heartbeat_at"])).total_seconds()
        assert fresh_age <= fleet.SUPERVISOR_CLAIM_STALE_SECONDS < stale_age

    def test_a_released_claim_has_no_beat_and_that_is_not_staleness(
            self, isolated_home):
        """The already-learned half of this lesson, pinned so the build does
        not regress it: §6.3 strips `heartbeat_at` on a clean stand-down, and
        `heartbeat_age_seconds is None` there means "correct release", never
        "40 minutes stale". Any canonical liveness value must keep saying so."""
        path = fleet.supervisor_dir() / "INCARNATION"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "incarnation_id": "inc-test", "claimed_at": "2026-08-09T00:00:00Z",
            "state": "released", "released_by_sid": SID,
            "released_at": "2026-08-09T01:00:00Z"}), encoding="utf-8")
        snap = fleet._supervisor_tier_snapshot()
        assert snap["state"] == "released"
        assert snap["heartbeat_age_seconds"] is None


# ---------------------------------------------------------------------------
# THE RULING, as an executable statement of what any canonical answer must
# preserve. These are the constraints §C of the report derives.
# ---------------------------------------------------------------------------

class TestWhatACanonicalAnswerMustPreserve:
    """DRIVEN, not grepped.

    The first version of this class asserted that certain SUBSTRINGS were
    present in `bin/fleet.py` -- the refusal message, and a comment containing
    the word SPARES. The w50 gate planted three mutants that break the
    properties these tests name while leaving those substrings in place, and
    all three survived the whole 20-test file:

      * `if not roster_ok:` -> `if not roster_ok and not args.force:`  (respawn
        proceeds on an unfetchable roster -- the "two live sessions under one
        name" branch), refusal text untouched;
      * `... if roster_ok else None` -> `...`  (`clean` DOOMS instead of
        sparing on an unreadable roster -- an irreversible deletion), the
        SPARES comment untouched;
      * the `_supervisor_gate` staleness disarm deleted, which the old test
        could not see because it re-implemented the comparison in the test
        instead of calling the gate.

    That is wave 35's shape in the file written to answer wave 35. Every test
    below now DRIVES the verb and asserts the OUTCOME, and each carries a
    control that proves the assertion can go the other way -- a refusal test
    that cannot observe a non-refusal is pinning nothing.
    """

    # --- respawn -------------------------------------------------------------

    def test_respawn_refuses_on_an_unfetchable_roster_even_with_force(
            self, sup_home, monkeypatch, capsys):
        """MUTANT M-B2. `--force` must NOT buy a bypass of the roster refusal:
        indeterminate is treated as alive, because a false-dead here is the
        file's own named unrecoverable invariant (`:8259`)."""
        _install_worker(sup_home)
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (False, "roster unavailable"))
        monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)

        for argv in (["respawn", "w", "--yes"], ["respawn", "w", "--yes", "--force"]):
            capsys.readouterr()
            rc = fleet.main(argv)
            err = capsys.readouterr().err
            assert rc != 0, (argv, err)
            assert "refusing respawn" in err, (argv, err)

    def test_control_respawn_gets_past_the_roster_gate_when_the_sid_is_gone(
            self, sup_home, monkeypatch):
        """The control the refusal test needs. Without it, the test above
        passes for any reason respawn happens to raise -- and `main` collapses
        every `FleetCliError` to rc 1, so "nonzero" alone proves little."""
        _install_worker(sup_home)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        monkeypatch.setattr(fleet, "_stop_native_session", lambda *a, **k: True)
        monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)

        with pytest.raises(_ReachedDispatch):
            fleet.cmd_respawn(SimpleNamespace(
                name="w", task=None, force=False, yes=True, nonce=None,
                max_budget_usd=None, setting_sources=None, token_ceiling=None))

    # --- clean ---------------------------------------------------------------

    def test_clean_spares_an_archived_carrier_when_the_roster_is_unreadable(
            self, sup_home, monkeypatch):
        """MUTANT M-C. An ARCHIVED record is "always doomed" in `cmd_clean` and
        never enters the G9 epoch freeze, so the unreadable-roster abstain is
        the ONLY thing standing between it and deletion. Sparing is reversible;
        deleting a live worker's journal is not."""
        _install_release_carrier(sup_home, archived=True)
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (False, "roster unavailable"))
        assert fleet.main(["clean", "--yes"]) == 0
        assert _CARRIER in fleet.load_registry()["workers"], (
            "clean deleted the release carrier on an UNREADABLE roster -- "
            "the abstain is gone")

    def test_control_clean_does_sweep_that_carrier_once_the_roster_says_gone(
            self, sup_home, monkeypatch):
        """The other limb. A spare that never releases is not an abstain, it is
        a permanent leak -- and a test that only ever asserts "still there"
        would pass against a `clean` that deletes nothing at all."""
        _install_release_carrier(sup_home, archived=True)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        assert fleet.main(["clean", "--yes"]) == 0
        assert _CARRIER not in fleet.load_registry()["workers"], (
            "clean spared the carrier even though the roster says the body is "
            "GONE -- the spare never releases")

    # --- the supervisor gate -------------------------------------------------

    def test_the_gate_arms_on_a_fresh_beat_and_disarms_on_a_stale_one(
            self, sup_home, monkeypatch):
        """MUTANT M-A. The old version of this test built
        `stale = now - (STALE + 60)` and asserted `fresh <= STALE < stale` --
        an identity about `timedelta` that is true for any positive constant
        and stays green with the entire gate deleted. This one CALLS the gate.

        Both limbs are the point: the ARM proves the gate exists, the DISARM
        proves the staleness branch is what turns it off. Deleting the disarm
        makes the second call raise."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "a-third-body")

        # FRESH: a held, non-legacy claim owned by someone else, no nonce
        # presented -> the gate must REFUSE.
        _write_claim(age_seconds=0)
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("clean")

        # STALE by one minute past the threshold -> DISARMED, no refusal.
        _write_claim(age_seconds=fleet.SUPERVISOR_CLAIM_STALE_SECONDS + 60)
        fleet._supervisor_gate("clean")   # must not raise

    def test_status_must_stay_liberal_and_advisory(self):
        """`dead-suspected` is surfaced, never auto-respawned -- so `status`
        may guess where `respawn` may not. A canonical answer that forces
        `status` to respawn's conservatism turns every ambiguous worker into
        a permanently-`working` row, which is disagreement 2 generalised."""
        assert "dead-suspected" in fleet.NATIVE_TERMINAL_STATUSES
        assert "dead-suspected" not in fleet._NATIVE_STICKY
