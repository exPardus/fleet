"""P1-6 -- the quarantine rename stops firing from UNLOCKED reads inside the
mutating verbs, and `kill`/`respawn` stop reporting *"unknown worker"* when the
truth is *"the registry could not be read"*.

WHAT WAS MEASURED at b3ec8d7, driven through `fleet.main()` against a real
invalid-JSON `state/fleet.json` in an isolated `FLEET_HOME`:

    fleet kill w1 --yes            | rc=1 | fleet.json=RENAMED-ASIDE | "unknown worker: 'w1'"
    fleet respawn w1 --yes         | rc=1 | fleet.json=RENAMED-ASIDE | "unknown worker: 'w1'"
    fleet kill nope --yes (HEALTHY)| rc=1 | fleet.json=intact        | "unknown worker: 'nope'"

The first two lines and the third are BYTE-IDENTICAL on stderr. The operator who
typed a correct worker name was told the name was wrong, on a run that had just
renamed their registry aside -- so the message misdirects the investigation AND
the evidence for the real cause is gone from where they would look for it.

THE ROOT CAUSE IS AN ORDERING ONE, and it is worth stating precisely because the
fix is not "stop quarantining". `cmd_respawn` documents the intended design in
prose at `bin/fleet.py:6266-6268`:

    resolve under the lock so a corrupt registry surfaces through
    load_registry's quarantine and an unknown worker gets the uniform error

That is correct and it still stands. What broke it is that `kill` and `respawn`
both call `_supervisor_lifecycle_target` FIRST (`:6488` / `:6230`), before any
lock, and that helper called `load_registry` -- which QUARANTINES. The rename
therefore happened at the unlocked pre-flight read, and by the time the
lock-held read ran, the file was ABSENT, not corrupt. `load_registry`'s
missing-file contract is `{"workers": {}}`, so the lock-held site saw an empty
roster and produced the uniform *"unknown worker"* error for a worker that was
in the registry all along. **The premature read STOLE the quarantine from the
site that was designed to perform it, and converted a corruption report into a
name error.**

`_registry_records_or_none`'s docstring is the doctrine these sites violated,
and it names the remedy's boundary exactly: *"Quarantining stays where it
belongs: the lock-holding verbs."*

WHY THE FIX IS `read_registry_no_repair` AND NOT `_registry_records_or_none`.
The obvious-looking swap is the wrong helper at all three sites:

  * `_registry_records_or_none` returns `dict | None` and CONFLATES
    *not_initialized* with *unreadable* (`_read_registry_readonly` answers
    `ok=False` for a missing file too). `_resolve_supervisor_lifecycle_target`
    must tell those apart: a MISSING registry genuinely has no record for the
    holder sid and the standing rc 2 *"matches no registry record"* refusal is
    the accurate answer, while a CORRUPT one must never be reported that way.
  * it also returns the `{"workers": ...}` PROJECTION, dropping sibling keys.
  * `read_registry_no_repair` is `load_registry` MINUS THE RENAME: same
    missing-file contract, same validator, same `RegistryCorruptError`. So it
    preserves each site's existing control flow exactly and keeps the REASON,
    which is what makes a non-misreporting refusal writable at all.

THE THREE SITES, AND THE THREE DIFFERENT ANSWERS ON AN UNREADABLE REGISTRY --
decided per site, because one blanket `or {}` would have relocated the very
misreport this file exists to remove:

  * `_supervisor_lifecycle_target` (`:6627` at b3ec8d7) -> **None**, "not the
    claim holder". Control flow unchanged, and the refusal still happens: the
    lock-held `load_registry` immediately downstream quarantines and reports
    the corruption accurately. This is the `:6254-6256` design working.
  * `_resolve_supervisor_lifecycle_target` (`:6596` at b3ec8d7) -> **explicit
    rc 3 refusal**. Falling through to the loop over an empty roster would land on
    *"holder sid matches no registry record"* -- the same misreport class,
    merely relocated. rc 3 and the wording mirror the sibling arm three
    branches up, which refuses a corrupt `supervisor/INCARNATION`
    with *"A destructive verb never decides blind"*: an unreadable registry is
    the same failure about the other half of the same lookup.
  * `_refetch_holder_record` (`:6777` at b3ec8d7) -> **`(fallback, False)`**,
    identical to its existing `except RegistryCorruptError` arm. `verified=False` already
    degrades loudly (kill rc 1 + `SUP-KILL-UNVERIFIED`, respawn halts before
    the successor dispatch), so nothing about the announced outcome changes --
    only that the operator's registry is still on disk when they go to look.

`_holder_is_limited` KEEPS its `load_registry` and is not a defect: its sole
caller `cmd_sup_boot` is lexically inside `with fleet_lock():`, which the census
below verifies from the AST rather than from the comment above it.
`wait_for_workers` / `cmd_wait` keep theirs too -- see
`TestTheUnlockedCensusIsPinned` for why, stated rather than left implicit.
"""
import argparse
import ast
import contextlib
import io
from pathlib import Path

import pytest

import fleet


CORRUPT = "{ this is not json"
SRC = Path(fleet.__file__).read_text(encoding="utf-8")
STALE = "2020-01-01T00:00:00Z"       # older than SUPERVISOR_CLAIM_STALE_SECONDS
HOLDER_SID = "sid-holder"
SUP_PIPE = "sup|L1|boot"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME. Every verb below is destructive; none of them may
    ever be pointed at the live fleet."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir(exist_ok=True)
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return tmp_path


def _rec(**over):
    base = {"session_id": "sid-1", "cwd": "C:/proj", "task": "t",
            "mode": "dontask", "status": "idle", "turns": 1,
            "cost_usd": 0.0, "last_activity": fleet.now_iso(),
            "dispatch_kind": "bg", "retired_sids": []}
    base.update(over)
    return base


def _seed(workers=None):
    fleet.save_registry({"workers": workers if workers is not None else {"w1": _rec()}})


def _corrupt():
    fleet.registry_path().write_text(CORRUPT, encoding="utf-8")
    return fleet.registry_path()


def _artifacts(home):
    return sorted(p.name for p in (home / "state").glob("fleet.json.corrupt.*"))


def _stale_claim(sid=HOLDER_SID):
    """A HELD claim whose heartbeat has aged out, so `_supervisor_gate` is
    disarmed (§4.13(e)) and the §10.4 resolver is actually reached. Without
    this the gate refuses first (rc 4, measured) and every assertion about the
    resolver below would pass vacuously against a path never walked."""
    fleet.write_incarnation({
        "incarnation_id": "inc-x", "session_id": sid, "state": "active",
        "lineage_id": "lin-x", "claimed_at": STALE, "heartbeat_at": STALE})


def _run(argv):
    """`fleet.main(argv)` with both streams captured. Returns (rc, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fleet.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# 1. The headline: the message names the CORRUPTION, never the worker's name
# ---------------------------------------------------------------------------

class TestTheVerbReportsCorruptionNotAnUnknownName:
    """The operator-facing half. `unknown worker` is a claim about the NAME the
    operator typed; the actual event was that the registry could not be read.
    Asserted as a NEGATIVE on the exact substring as well as a positive on the
    real cause -- a message that says both would still send the reader after
    their own typo first."""

    @pytest.mark.parametrize("verb", ["kill", "respawn"])
    def test_the_message_does_not_blame_the_name(self, home, verb):
        _seed()
        _corrupt()
        rc, _out, err = _run([verb, "w1", "--yes"])
        assert rc != 0
        assert "unknown worker" not in err, (
            f"`fleet {verb} w1` over a CORRUPT registry reported a name error. "
            f"The name was right; the registry was unreadable. stderr: {err!r}")

    @pytest.mark.parametrize("verb", ["kill", "respawn"])
    def test_the_message_names_the_registry(self, home, verb):
        _seed()
        _corrupt()
        _rc, _out, err = _run([verb, "w1", "--yes"])
        assert "registry" in err.lower(), err

    def test_the_seed_a_genuinely_unknown_name_STILL_says_unknown_worker(self, home):
        """THE NON-VACUITY SEED, and it is not optional: the two assertions
        above are negatives on a substring, so a build in which `kill` stopped
        saying `unknown worker` for ANY reason would make them both pass while
        the uniform error had simply been deleted. This proves the phrase is
        still reachable and still means what it says."""
        _seed()
        rc, _out, err = _run(["kill", "nope", "--yes"])
        assert rc != 0
        assert "unknown worker" in err, err

    def test_the_seed_the_healthy_and_corrupt_messages_actually_DIFFER(self, home):
        """The property in its sharpest form, and the one the measurement
        found: at b3ec8d7 these two stderr strings were byte-identical apart
        from the name. If they ever converge again this goes red even if both
        happen to satisfy the assertions above."""
        _seed()
        _rc, _o, healthy = _run(["kill", "nope", "--yes"])
        _corrupt()
        _rc, _o, corrupt = _run(["kill", "w1", "--yes"])
        assert healthy.replace("nope", "X") != corrupt.replace("w1", "X"), (
            f"a corrupt registry and a mistyped name produce the same report: "
            f"{corrupt!r}")


# ---------------------------------------------------------------------------
# 2. The structural half: nothing renames the registry before the lock
# ---------------------------------------------------------------------------

class TestTheRenameOnlyEverHappensUnderTheLock:
    """`_registry_records_or_none`'s docstring: *"Quarantining stays where it
    belongs: the lock-holding verbs."* Pinned as a BEHAVIOURAL property rather
    than by naming the two helpers that were wrong, because the class this
    repo keeps re-finding is *a NEW read added ahead of the lock* -- and a test
    that names today's offenders cannot see tomorrow's.

    `fleet_lock` is poisoned so that taking it aborts the verb. Anything the
    verb managed to do to `state/fleet.json` before that point was, by
    construction, done without the lock."""

    @pytest.fixture
    def lock_is_poison(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("reached the lock")
        monkeypatch.setattr(fleet, "fleet_lock", _boom)

    def _assert_untouched(self, home, path):
        assert path.exists(), (
            "state/fleet.json was renamed aside BEFORE the verb took "
            "`fleet.lock` -- the quarantine is a write, and an unlocked write "
            "races every other fleet command")
        assert path.read_text(encoding="utf-8") == CORRUPT
        assert _artifacts(home) == []

    @pytest.mark.parametrize("verb", ["kill", "respawn"])
    def test_an_ordinary_name_renames_nothing_before_the_lock(
            self, home, lock_is_poison, verb):
        _seed()
        path = _corrupt()
        with pytest.raises(AssertionError, match="reached the lock"):
            fleet.main([verb, "w1", "--yes"])
        self._assert_untouched(home, path)

    @pytest.mark.parametrize("verb", ["kill", "respawn"])
    def test_the_LOGICAL_supervisor_name_renames_nothing_before_the_lock(
            self, home, lock_is_poison, verb):
        """The other entry shape, and the one an ordinary-name fixture cannot
        reach: `supervisor` routes into `_resolve_supervisor_lifecycle_target`,
        a different helper with a different (uncaught) call.

        It never reaches the lock at all -- it refuses in pre-flight -- so
        `lock_is_poison` is here to prove that, not to be triggered. Driven
        through `main` and graded on rc rather than with `pytest.raises`,
        because `main` CATCHES both `SupervisorLifecycleRefusal` and
        `RegistryCorruptError` and returns their codes -- a `raises` block here
        would never fire and the test would report on nothing."""
        _seed({SUP_PIPE: _rec(session_id=HOLDER_SID)})
        path = _corrupt()
        _stale_claim()
        rc, _out, _err = _run([verb, "supervisor", "--yes"])
        assert rc != 0
        self._assert_untouched(home, path)

    def test_the_seed_the_lock_poison_actually_fires(self, home, lock_is_poison):
        """Without this, a verb that refused before ever touching the registry
        would satisfy every assertion above for the wrong reason."""
        _seed()
        with pytest.raises(AssertionError, match="reached the lock"):
            fleet.main(["kill", "w1", "--yes"])

    def test_the_seed_the_lock_held_site_STILL_quarantines(self, home):
        """The half that must NOT change, stated as its own test because the
        cheapest way to make this file green is to stop quarantining
        altogether -- and the 2026-07-27 operator gate did not ask for that.
        With the lock available, `kill` quarantines exactly once, from the
        lock-held read, and says so."""
        _seed()
        path = _corrupt()
        rc, _out, err = _run(["kill", "w1", "--yes"])
        assert rc != 0
        assert not path.exists(), (
            "nobody quarantined the corrupt registry at all -- the rename was "
            "meant to MOVE to the lock-held read, not to disappear")
        assert len(_artifacts(home)) == 1, _artifacts(home)
        assert "quarantin" in err.lower(), err


# ---------------------------------------------------------------------------
# 3. Per-site unit pins, including the missing-vs-corrupt distinction
# ---------------------------------------------------------------------------

class TestSupervisorLifecycleTargetOnAnUnreadableRegistry:
    """The `:6627`-at-b3ec8d7 site. Answers None -- "not the claim holder" --
    exactly as it does
    for an unknown name, and leaves the file alone. The refusal is not lost: it
    moves to the lock-held read, which is what `TestTheVerbReports...` drives."""

    def test_it_returns_None_and_touches_nothing(self, home):
        _seed()
        path = _corrupt()
        assert fleet._supervisor_lifecycle_target("kill", "w1") is None
        assert path.read_text(encoding="utf-8") == CORRUPT
        assert _artifacts(home) == []

    def test_a_MISSING_registry_is_unchanged_too(self, home):
        """The contract `read_registry_no_repair` shares with `load_registry`:
        a missing file is `{"workers": {}}`, not an error. A helper that raised
        here would break every fresh install."""
        assert fleet._supervisor_lifecycle_target("kill", "w1") is None


class TestResolveSupervisorLifecycleTargetOnAnUnreadableRegistry:
    """The `:6596`-at-b3ec8d7 site. Where a bare `or {}` would have smuggled a policy:
    an empty roster falls through to *"holder sid matches no registry
    record"*, which is a claim about the REGISTRY'S CONTENTS made by a caller
    that could not read the registry."""

    def test_a_corrupt_registry_refuses_rc3_and_names_the_cause(self, home):
        _seed({SUP_PIPE: _rec(session_id=HOLDER_SID)})
        path = _corrupt()
        _stale_claim()
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet._resolve_supervisor_lifecycle_target("kill")
        assert exc.value.rc == 3, (
            "an unreadable registry is an INDETERMINATE holder verdict on a "
            "destructive verb -- the same rc 3 the corrupt-INCARNATION arm "
            "three branches up already answers")
        msg = str(exc.value)
        assert "matches no registry record" not in msg, (
            f"refused with a claim about the registry's CONTENTS while unable "
            f"to read the registry: {msg!r}")
        assert "registry" in msg.lower()
        assert "doctor" in msg
        assert path.read_text(encoding="utf-8") == CORRUPT
        assert _artifacts(home) == []

    def test_a_MISSING_registry_still_refuses_rc2_matching_no_record(self, home):
        """THE REGRESSION GUARD FOR THE FIX ITSELF, and the reason
        `_registry_records_or_none` is the wrong helper here: it answers None
        for a missing file as well as a corrupt one, so a None-keyed refusal
        would report a fresh install as an unreadable registry. A missing
        registry genuinely holds no record for the holder sid, and rc 2 is the
        accurate standing answer."""
        _stale_claim()
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet._resolve_supervisor_lifecycle_target("kill")
        assert exc.value.rc == 2
        assert "matches no registry record" in str(exc.value)

    def test_a_healthy_registry_still_resolves_the_holder(self, home):
        """The happy path, so a refusal added for the corrupt case cannot have
        swallowed the ordinary one."""
        _seed({SUP_PIPE: _rec(session_id=HOLDER_SID)})
        _stale_claim()
        name, rec, claim = fleet._resolve_supervisor_lifecycle_target("kill")
        assert name == SUP_PIPE
        assert rec["session_id"] == HOLDER_SID
        assert claim["incarnation_id"] == "inc-x"


class TestRefetchHolderRecordOnAnUnreadableRegistry:
    """The `:6777`-at-b3ec8d7 site. The announced outcome is unchanged --
    `verified=False`, which
    already degrades loudly -- and the registry survives. Both halves matter:
    a fix that also silenced the degradation would trade a destroyed file for a
    fail-open kill, which is the CRIT-1 the `verified` flag exists for."""

    def test_it_reports_unverified_and_touches_nothing(self, home):
        _seed()
        path = _corrupt()
        fallback = {"session_id": "sid-old"}
        rec, verified = fleet._refetch_holder_record("w1", fallback)
        assert verified is False
        assert rec is fallback
        assert path.read_text(encoding="utf-8") == CORRUPT
        assert _artifacts(home) == []

    def test_a_readable_registry_still_verifies(self, home):
        _seed()
        rec, verified = fleet._refetch_holder_record("w1", {"session_id": "sid-old"})
        assert verified is True
        assert rec["session_id"] == "sid-1"


# ---------------------------------------------------------------------------
# 4. The census, pinned -- so the NEXT unlocked read is loud
# ---------------------------------------------------------------------------

def _unlocked_load_registry_scopes(source: str = SRC) -> dict:
    """{scope: [lines]} for every `load_registry` call NOT lexically inside a
    `with fleet_lock():` block in its own enclosing scope.

    Scope attribution and alias resolution are deliberately the same rules
    `tests/test_load_registry_callers.py::_callers` uses, so the two files can
    never disagree about the population. What this adds is the axis that file
    explicitly declines to decide: LOCK-HOLDING.

    WHAT IT CAN AND CANNOT DECIDE, said plainly. `fleet_lock()` is frequently
    taken by the CALLER, several frames up, so "not lexically locked" is NOT
    the same as "unlocked at runtime" -- `_holder_is_limited` is exactly that
    case and is correct. The assertion below is therefore an ALLOWLIST of
    scopes, each with the interprocedural argument written out once, and NOT a
    claim that a lexically-unlocked call is a defect. Adding a new one is then
    a deliberate edit with a reviewer looking at it, which is the property five
    recurrences of this class have wanted."""
    tree = ast.parse(source)
    aliases = {"load_registry"}
    changed = True
    while changed:                                  # module-level alias fixpoint
        changed = False
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Name) and node.value.id in aliases):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True

    def calls(node):
        return [n for n in ast.walk(node) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id in aliases]

    def locked(node):
        out = set()
        for w in ast.walk(node):
            if isinstance(w, ast.With) and any(
                    isinstance(i.context_expr, ast.Call)
                    and isinstance(i.context_expr.func, ast.Name)
                    and i.context_expr.func.id == "fleet_lock" for i in w.items):
                out |= {c.lineno for c in calls(w)}
        return out

    found = {}

    def record(scope, node):
        free = sorted({c.lineno for c in calls(node)} - locked(node))
        if free:
            found[scope] = sorted(set(found.get(scope, [])) | set(free))

    def scan(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not prefix and node.name == "load_registry":
                    continue                        # the definition itself
                record(prefix + node.name, node)
            elif isinstance(node, ast.ClassDef):
                scan(node.body, prefix + node.name + ".")
            else:
                record((prefix + "<class body>") if prefix else "<module>", node)

    scan(tree.body, "")
    return found


# Every scope permitted to call `load_registry` OUTSIDE a lexical
# `with fleet_lock():`. Each entry carries the interprocedural argument, because
# that argument is the only thing that makes the entry safe and the next reader
# cannot re-derive it from the line alone.
#
# TO ADD AN ENTRY: prove the call is lock-held by a caller, or that quarantining
# from this path is what the operator asked for. If it is a pre-flight read, a
# hot path, or a view, the answer is no and the fix is `read_registry_no_repair`
# (same contract, no rename) or `_read_registry_readonly` (never raises).
UNLOCKED_ALLOWED = {
    # Lock-held by its ONE caller, `cmd_sup_boot`, lexically inside
    # `with fleet_lock():` -- verified from the AST by
    # `test_holder_is_limited_really_is_lock_held_by_its_caller` below rather
    # than taken from the comment above the call, since a comment is a claim.
    # `_registry_records_or_none`'s docstring blesses this site by name.
    "_holder_is_limited",
    # `fleet wait` is a CLI verb the operator invoked directly and which
    # PERSISTS the transitions it observes, so quarantining is the designed
    # behaviour (`tests/test_load_registry_callers.py`'s admission rule). More
    # to the point for THIS file: `cmd_wait`'s first act is a LOCK-HELD
    # `load_registry` (`:5071-5072`), so a registry that is corrupt when the
    # verb starts is quarantined and refused from under the lock before any of
    # these three reads is reached. The residual is a registry that becomes
    # corrupt DURING a long wait; that raises `RegistryCorruptError` with the
    # quarantine named, so it destroys evidence but does NOT misreport, which
    # is why P1-6 left it alone rather than folding an unrelated policy
    # decision (refuse the wait, or degrade it?) into a misreport fix.
    "cmd_wait", "wait_for_workers",
}


class TestTheUnlockedCensusIsPinned:
    """THE GENERALISATION. Every previous instance of this class was found by a
    person reading a diff, and each fix named the sites it knew about; this
    turns the enumeration into a harness so the NEXT one is a red test.

    Measured at b3ec8d7: 52 `load_registry` call sites across 30 scopes, 45
    lexically lock-held and 7 not. The 7 were `wait_for_workers:5011`,
    `cmd_wait:5110`, `cmd_wait:5167`, `_resolve_supervisor_lifecycle_target:6596`,
    `_supervisor_lifecycle_target:6627`, `_refetch_holder_record:6777` and
    `_holder_is_limited:12241`. The brief for this lane named two of them and
    misattributed both to `cmd_kill` -- whose own call (`:6501`) is lock-held."""

    def test_the_matcher_finds_call_sites_at_all(self):
        """Seed. A matcher that found nothing would make the assertion below
        pass vacuously, which is the failure mode this repo names most often."""
        tree = ast.parse(SRC)
        total = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "load_registry")
        assert total >= 40, (
            f"only {total} `load_registry` calls found -- the matcher rotted")

    def test_the_matcher_distinguishes_locked_from_unlocked(self):
        """The other half of the seed, and the one that matters: a matcher that
        called EVERYTHING locked would report an empty offender set forever."""
        planted = (
            "def a():\n"
            "    with fleet_lock():\n"
            "        return load_registry()\n"
            "def b():\n"
            "    return load_registry()\n"
            "def c():\n"
            "    with some_other_lock():\n"
            "        return load_registry()\n")
        assert sorted(_unlocked_load_registry_scopes(planted)) == ["b", "c"]

    def test_a_planted_unlocked_read_in_a_new_helper_is_caught(self):
        """The evasion this file exists to close, planted as a real call: a
        helper that looks like a read, called from a verb's pre-flight."""
        planted = (
            "def _new_preflight(name):\n"
            "    return load_registry().get('workers', {}).get(name)\n")
        found = _unlocked_load_registry_scopes(planted)
        assert "_new_preflight" in found
        assert "_new_preflight" not in UNLOCKED_ALLOWED

    def test_no_unallowlisted_scope_calls_load_registry_outside_the_lock(self):
        """THE DETECTOR."""
        found = _unlocked_load_registry_scopes()
        offenders = {s: lines for s, lines in found.items()
                     if s not in UNLOCKED_ALLOWED}
        assert offenders == {}, (
            f"scope(s) calling `load_registry` outside a lexical "
            f"`with fleet_lock():`: { {s: v for s, v in sorted(offenders.items())} }. "
            f"`load_registry` QUARANTINES a corrupt registry -- it RENAMES the "
            f"file aside, which is a WRITE, and an unlocked write both races "
            f"every other fleet command and converts *corrupt* into *absent* "
            f"for whatever reads next. If this is a pre-flight or diagnostic "
            f"read, use `read_registry_no_repair` (identical contract, no "
            f"rename). If a CALLER holds the lock, add the scope to "
            f"UNLOCKED_ALLOWED with that argument written out.")

    def test_the_allowlist_has_no_dead_entries(self):
        """An entry for a scope that no longer has an unlocked call is standing
        permission nobody is using, and the next reader would take it as
        evidence that such a call is fine here."""
        found = set(_unlocked_load_registry_scopes())
        dead = sorted(UNLOCKED_ALLOWED - found)
        assert dead == [], (
            f"UNLOCKED_ALLOWED entries with no unlocked call left: {dead} -- "
            f"delete them rather than leaving standing permission")

    def test_holder_is_limited_really_is_lock_held_by_its_caller(self):
        """The one interprocedural argument in `UNLOCKED_ALLOWED`, checked
        instead of trusted. `_holder_is_limited` is allowlisted SOLELY because
        `cmd_sup_boot` calls it under the lock; if that call ever moves out of
        the `with` block, the entry silently becomes a live defect -- which is
        exactly how `_supervisor_gate` earned its place in this class's
        history (fix wave 2, MAJOR 1: allowlisted under "all inside
        `fleet_lock()`", which was false)."""
        tree = ast.parse(SRC)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "cmd_sup_boot")
        calls = {c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Name)
                 and c.func.id == "_holder_is_limited"}
        locked = set()
        for w in ast.walk(fn):
            if isinstance(w, ast.With) and any(
                    isinstance(i.context_expr, ast.Call)
                    and isinstance(i.context_expr.func, ast.Name)
                    and i.context_expr.func.id == "fleet_lock" for i in w.items):
                locked |= {c.lineno for c in ast.walk(w) if isinstance(c, ast.Call)
                           and isinstance(c.func, ast.Name)
                           and c.func.id == "_holder_is_limited"}
        assert calls, (
            "cmd_sup_boot no longer calls `_holder_is_limited` -- if that is "
            "intended, drop the UNLOCKED_ALLOWED entry and delete this test")
        assert calls == locked, (
            f"cmd_sup_boot calls `_holder_is_limited` OUTSIDE `with "
            f"fleet_lock():` at {sorted(calls - locked)}. That helper calls "
            f"`load_registry`, so the call is now an unlocked quarantine on the "
            f"boot path and its UNLOCKED_ALLOWED entry is no longer true.")

    def test_the_two_preflight_helpers_do_not_regain_load_registry(self):
        """Named individually so a revert is LOUD rather than merely
        unallowlisted. `test_no_unallowlisted_scope...` would also catch it,
        but it reports a generic offender and the next reader's first instinct
        on that failure is to add the name to the allowlist -- which is
        precisely how `_supervisor_gate` and `_resolve_worker_target` got their
        standing permission in the sibling file."""
        tree = ast.parse(SRC)
        for name in ("_supervisor_lifecycle_target",
                     "_resolve_supervisor_lifecycle_target",
                     "_refetch_holder_record"):
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == name)
            hits = sorted(c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)
                          and isinstance(c.func, ast.Name)
                          and c.func.id == "load_registry")
            assert hits == [], (
                f"{name} calls `load_registry` again at {hits}. It is a "
                f"PRE-FLIGHT read that runs before `kill`/`respawn` take "
                f"`fleet.lock` (`bin/fleet.py:6500` / `:6230`), and the rename "
                f"there steals the quarantine from the lock-held read -- after "
                f"which the operator is told `unknown worker` about a worker "
                f"that was in the registry. Use `read_registry_no_repair`.")
