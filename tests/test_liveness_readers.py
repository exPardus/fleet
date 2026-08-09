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
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
# THE CENSUS, as pins. A census is a claim about a count; a claim about a
# count that nothing re-derives is the defect this repo is named for.
# ---------------------------------------------------------------------------

class TestTheCensus:
    def test_roster_live_sids_has_eleven_call_sites_not_ten(self, tree):
        """The brief said 10, counted by grep. Grep sees 14 lines: 11 calls,
        1 def, 2 docstring mentions. The AST cannot see the last three."""
        calls = _call_lines(tree, "_roster_live_sids")
        assert len(calls) == 11, f"call sites moved: {calls}"

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
                 "_supervisor_tier_snapshot", "_dispatch_grace_active"]
        defined = {n.name for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert not [n for n in names if n not in defined]

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
        `_roster_live_sids` calls load-bearing is simply absent. On the
        2026-08-09 win32 roster this shape had ZERO instances (69 `done`
        entries, none carrying keys), so it is unreachable there today. It is
        reachable on posix: `_roster_live_sids`'s own docstring records
        observing it on macOS 2026-07-19."""
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


class TestTheWindowsParenthetical:
    """`(On Windows the two conditions agree -- done entries lose pid/status.)`

    MEASURED 2026-08-09 against 137 live win32 roster entries: the sentence's
    FORWARD direction held (69 `done`, zero carrying pid/status), so the
    predecessor's measurement did not reproduce. But "the two conditions
    agree" is a BICONDITIONAL, and the reverse direction is false with 60
    counter-examples. These fixtures carry the shapes of those 60."""

    KEYLESS_NOT_DONE = [
        {"sessionId": "s-blocked", "state": "blocked"},   # 32 live instances
        {"sessionId": "s-stopped", "state": "stopped"},   # 26 live instances
        {"sessionId": "s-failed", "state": "failed"},     # 2 live instances
    ]

    def test_the_reverse_direction_of_the_biconditional_is_false(self):
        for entry in self.KEYLESS_NOT_DONE:
            assert entry["state"] != "done"
            assert "pid" not in entry and "status" not in entry
            assert fleet._roster_live_sids([entry]) == set(), (
                "not-done and yet not live: the two conditions do NOT agree")

    def test_the_done_clause_is_inert_on_a_windows_shaped_roster(self):
        """Why nobody noticed. On win32 the key-presence test is strictly
        stronger, so dropping the `done` clause changes no answer at all --
        which is precisely what makes the comment safe to believe and the
        divergence safe to ship."""
        roster = self.KEYLESS_NOT_DONE + [
            {"sessionId": "s-done", "state": "done"},
            {"sessionId": "s-live", "state": "working", "status": "busy", "pid": 7},
        ]
        with_clause = fleet._roster_live_sids(roster)
        without_clause = {e["sessionId"] for e in roster
                          if "status" in e or "pid" in e}
        assert with_clause == without_clause == {"s-live"}


# ---------------------------------------------------------------------------
# THE FOURTH READER -- not named in the brief, and it answers the OPPOSITE way
# on every one of the 60 entries above.
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
    def test_respawn_must_stay_conservative_toward_alive(self):
        """`_cmd_respawn_native` refuses on an UNFETCHABLE roster
        (bin/fleet.py:8225) -- indeterminate is treated as alive, because a
        false-dead here is "never two live sessions under one name", which is
        the named unrecoverable invariant. Any canonical answer that lets
        respawn proceed on `unknown` is a regression."""
        src = FLEET_PY.read_text(encoding="utf-8")
        assert "refusing respawn " in src and "until the old session's liveness" in src

    def test_clean_must_stay_conservative_toward_alive_too(self):
        """`cmd_clean` passes `live_sids=None` on an unreadable roster and the
        predicate SPARES on None (bin/fleet.py:9766-9767)."""
        assert fleet._roster_live_sids([]) == set()
        src = FLEET_PY.read_text(encoding="utf-8")
        assert 'None means "the roster is unknown", which SPARES' in src

    def test_status_must_stay_liberal_and_advisory(self):
        """`dead-suspected` is surfaced, never auto-respawned -- so `status`
        may guess where `respawn` may not. A canonical answer that forces
        `status` to respawn's conservatism turns every ambiguous worker into
        a permanently-`working` row, which is disagreement 2 generalised."""
        assert "dead-suspected" in fleet.NATIVE_TERMINAL_STATUSES
        assert "dead-suspected" not in fleet._NATIVE_STICKY
