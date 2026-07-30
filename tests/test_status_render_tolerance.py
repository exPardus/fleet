"""W15 `status-crash`: a status view must render a short record, never raise.

THE DEFECT THIS EXISTS FOR. Measured 2026-07-30 at `2e23582`, against a real
registry recovered from the fleet home
(`state/fleet.json.testpollution.20260729T225839Z`, 366 bytes, forensic
evidence of the ULTRAREVIEW-R2 isolation escape -- copied, never consumed):

    NAME                STATUS     TURNS     COST  MIN-AGO  MAIL   ATTACH  FLAGS
    Traceback (most recent call last):
      ...
      File "bin/fleet.py", line 4156, in cmd_status
        _print_status_table({"workers": display}, names)
      File "bin/fleet.py", line 4242, in _print_status_table
        cost_s = f"{rec['cost_usd']:>9.2f}"
    KeyError: 'cost_usd'

rc=1, header printed, **zero rows**. Both workers vanished from the one surface
that tells the operator what the fleet is doing, at the moment something was
already wrong. That is the same failure mode as a view that quarantines
(`docs/specs/terminal-surface.md` D4, `tests/test_views_doctrine.py`): the
operator loses their evidence. `unknown` must be a RENDERED WORD -- never
silence, never a traceback (`knowledge/lessons.md#2026-07-27-day5-surface`).

ROOT CAUSE, not symptom. `new_worker_record`'s own docstring states this file's
additive-schema doctrine verbatim -- *"readers everywhere use .get(..., None) so
a record written before these fields existed loads cleanly"*. `status_snapshot`
obeys it completely. `cmd_status`'s authoritative path and the two table
printers did not: they direct-subscript baseline fields, i.e. they assume every
record on disk matches TODAY's 25-field schema. A pre-field record, a
hand-edited registry, a partially-written one, or a test fixture breaks that
assumption -- and the crash class is the whole set of such fields, not
`cost_usd` alone.

THE FIXTURE IS A SHAPE, NOT A PATH. The recovered registry lives in the fleet
home, outside this repo, and a test that reads it would pass only on this
machine. `FIXTURE_SHAPE` below is that file's record shape transcribed
verbatim; `test_the_recovered_fixture_shape_is_still_the_crashing_shape`
documents the provenance so a reader can re-derive it.

WHY THIS IS PARAMETRIZED PER FIELD. Fixing one subscript MOVES the crash to the
next one: with `status` absent the raise is at `:4132`, and only once that is
guarded does `_worker_flags`'s `record["status"]` at `:2934` become reachable.
A pin that covers `cost_usd` alone would go green while `fleet status` still
died on the very next field -- "a pin that advertises totality while iterating a
subset". So the parametrization is over EVERY baseline field, derived from
`new_worker_record()` at runtime: a field added to the schema tomorrow is
covered the day it is added, with no edit here.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402


# The placeholder token. ONE token, and not a new invention: `_print_status_table`
# already rendered "?" for an unparseable `last_activity`, `_print_snapshot_table`
# already rendered it for an unknown age, and `status_snapshot` already used it as
# its `status` fallback. Anything the tables cannot format renders as this.
UNKNOWN = "?"

# Transcribed from state/fleet.json.testpollution.20260729T225839Z (fleet home,
# read-only). Four keys, and none of the four the table formats.
FIXTURE_SHAPE = {
    "session_id": "11111111-1111-4111-8111-111111111111",
    "retired_sids": [],
    "status": "working",
    "archived_at": None,
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "mailbox").mkdir()
    # The roster fetch shells out to `claude`. This suite is about record
    # SHAPE, and an empty roster is a real outcome (that is what
    # `_fetch_agents_roster` yields whenever `claude` is absent).
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
    return tmp_path


def _write(home, workers):
    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers}), encoding="utf-8")


def _args(name=None, **kw):
    base = dict(name=name, json=False, stale_ok=False, all=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _full():
    return fleet.new_worker_record("11111111-1111-4111-8111-111111111111",
                                   "C:/proj", "do the thing", "dontask")


def _rows(out, names):
    """The rendered line for each worker name, keyed by name."""
    found = {}
    for line in out.splitlines():
        for n in names:
            if line.startswith(n):
                found[n] = line
    return found


def _column(out, name, header_label):
    """One named column's cell for one worker row, stripped.

    The slice is DERIVED from the printed header rather than hardcoded: every
    column in both tables is a fixed-width field and the header label sits at
    its right edge, so `label_end - width` is the cell start. Asserting on the
    whole line instead would let a `?` leaking from the AGE column satisfy a
    claim about COST -- which is exactly how a placeholder pin goes vacuous.
    """
    lines = out.splitlines()
    header = next(l for l in lines if l.lstrip().startswith("NAME"))
    widths = {"TURNS": 6, "COST": 9, "AGE": 9, "MIN-AGO": 9, "MAIL": 6}
    end = header.index(header_label) + len(header_label)
    return _rows(out, [name])[name][end - widths[header_label]:end].strip()


BASELINE_FIELDS = sorted(_full())


# ---------------------------------------------------------------------------
# The reported crash, from the recovered fixture's own shape.
# ---------------------------------------------------------------------------

class TestTheReportedCrash:

    def test_fleet_status_renders_the_recovered_fixture_and_exits_zero(
            self, home, capsys):
        """The exact reproduction, as a pin. rc 0, both rows, no traceback."""
        _write(home, {"sup|inc-L|boot": dict(FIXTURE_SHAPE),
                      "w1": dict(FIXTURE_SHAPE,
                                 session_id="22222222-2222-4222-8222-222222222222")})
        rc = fleet.cmd_status(_args())
        out = capsys.readouterr().out
        assert rc == 0, "fleet status must exit 0 on a short record"
        rows = _rows(out, ["sup|inc-L|boot", "w1"])
        assert set(rows) == {"sup|inc-L|boot", "w1"}, (
            f"a short record swallowed rows -- rendered:\n{out}")
        for name in rows:
            assert _column(out, name, "COST") == UNKNOWN, (
                f"{name}: the COST cell does not read {UNKNOWN!r} for a record "
                f"that carries no cost_usd -- rendered:\n{out}")
            assert _column(out, name, "TURNS") == UNKNOWN, (
                f"{name}: the TURNS cell does not read {UNKNOWN!r} for a record "
                f"that carries no turns -- rendered:\n{out}")

    def test_the_recovered_fixture_shape_is_still_the_crashing_shape(self):
        """Provenance guard for FIXTURE_SHAPE.

        The real file is outside the repo, so this asserts the property that
        made it the fixture: it carries NONE of the fields the status table
        formats. If someone "helpfully" fills the shape in, the reproduction
        above stops reproducing and this says so instead of going quietly
        green.
        """
        formatted = {"cost_usd", "turns"}
        assert not (formatted & set(FIXTURE_SHAPE)), (
            "FIXTURE_SHAPE now carries a field the status table formats, so it "
            "no longer reproduces the W15 crash. Re-derive it from "
            "state/fleet.json.testpollution.20260729T225839Z (READ ONLY).")


# ---------------------------------------------------------------------------
# The class: EVERY baseline field, one at a time, on every status surface.
# ---------------------------------------------------------------------------

class TestNoAbsentFieldCrashesAStatusView:
    """Derived from `new_worker_record()`, so the schema extends the pin."""

    @pytest.mark.parametrize("field", BASELINE_FIELDS)
    def test_fleet_status_survives_the_field_being_absent(
            self, home, capsys, field):
        rec = _full()
        del rec[field]
        _write(home, {"w1": rec})
        rc = fleet.cmd_status(_args())
        out = capsys.readouterr().out
        assert rc == 0, f"`fleet status` did not exit 0 with {field!r} absent"
        assert "w1" in _rows(out, ["w1"]), (
            f"the row vanished with {field!r} absent -- rendered:\n{out}")

    @pytest.mark.parametrize("field", BASELINE_FIELDS)
    def test_fleet_status_stale_ok_survives_the_field_being_absent(
            self, home, capsys, field):
        rec = _full()
        del rec[field]
        _write(home, {"w1": rec})
        rc = fleet.cmd_status(_args(stale_ok=True))
        out = capsys.readouterr().out
        assert rc == 0, f"`status --stale-ok` did not exit 0 with {field!r} absent"
        assert "w1" in _rows(out, ["w1"]), (
            f"the row vanished with {field!r} absent -- rendered:\n{out}")

    @pytest.mark.parametrize("field", BASELINE_FIELDS)
    def test_fleet_status_json_survives_the_field_being_absent(
            self, home, capsys, field):
        rec = _full()
        del rec[field]
        _write(home, {"w1": rec})
        rc = fleet.cmd_status(_args(json=True))
        out = capsys.readouterr().out
        assert rc == 0, f"`status --json` did not exit 0 with {field!r} absent"
        assert json.loads(out)["workers"][0]["name"] == "w1"

    @pytest.mark.parametrize("field", BASELINE_FIELDS)
    def test_the_helpers_the_table_calls_survive_the_field_being_absent(
            self, home, field):
        """`_worker_flags` is the MASKED site.

        It direct-subscripted `record["status"]` five times and
        `record["session_id"]` once. It never surfaced in a whole-command sweep
        because `cmd_status:4132` raised on the same record first -- so guarding
        only the sites a command-level sweep can see leaves this one armed,
        waiting for the guard upstream of it to land.
        """
        rec = _full()
        del rec[field]
        fleet._worker_flags(rec)          # must not raise
        fleet._attach_age_seconds(rec)    # must not raise
        fleet.is_native(rec)              # must not raise

    def test_a_record_with_no_session_id_does_not_claim_another_files_mail(
            self, home):
        """The `sid and` guard in `_worker_flags`, made falsifiable.

        Found by fault injection: deleting that guard reddened NOTHING, because
        `_pending_mail_count` interpolates whatever it is given and a missing
        file simply counts 0. The guard is still load-bearing -- without it an
        absent sid formats to the literal string "None" and the flag is decided
        by whether `mailbox/None.md` happens to exist. An unpinned guard is a
        guard the next author deletes as dead code, so here is the file.
        """
        (home / "mailbox" / "None.md").write_text("stray", encoding="utf-8")
        rec = dict(_full(), session_id=None, status="idle")
        assert "idle+mail" not in fleet._worker_flags(rec), (
            "a record with no session_id was flagged idle+mail on the strength "
            "of mailbox/None.md -- it read another file's mail")


# ---------------------------------------------------------------------------
# The value-corruption arm: field PRESENT, but not something you can format.
# A hand-edited registry is the stated origin of this fixture, and a
# hand-edited registry holds strings and nulls, not just holes.
# ---------------------------------------------------------------------------

POISONED = [
    ("cost_usd", "abc"),
    ("cost_usd", None),
    ("cost_usd", []),
    ("cost_usd", float("nan")),
    ("cost_usd", -5.0),
    ("turns", None),
    ("turns", "many"),
    ("turns", []),
    ("status", None),
    ("status", 7),
]


class TestNoUnformattableValueCrashesAStatusView:

    @pytest.mark.parametrize("field,value", POISONED,
                             ids=[f"{f}={v!r}" for f, v in POISONED])
    def test_fleet_status_survives_it(self, home, capsys, field, value):
        rec = _full()
        rec[field] = value
        _write(home, {"w1": rec})
        rc = fleet.cmd_status(_args())
        out = capsys.readouterr().out
        assert rc == 0, f"`fleet status` did not exit 0 with {field}={value!r}"
        assert "w1" in _rows(out, ["w1"]), f"row vanished -- rendered:\n{out}"

    @pytest.mark.parametrize("field,value", POISONED,
                             ids=[f"{f}={v!r}" for f, v in POISONED])
    def test_fleet_status_stale_ok_survives_it(self, home, capsys, field, value):
        rec = _full()
        rec[field] = value
        _write(home, {"w1": rec})
        rc = fleet.cmd_status(_args(stale_ok=True))
        out = capsys.readouterr().out
        assert rc == 0, f"`status --stale-ok` did not exit 0 with {field}={value!r}"
        assert "w1" in _rows(out, ["w1"]), f"row vanished -- rendered:\n{out}"

    @pytest.mark.xfail(strict=True, reason=(
        "OUT OF SCOPE FOR W15, AND DELIBERATELY LEFT VISIBLE. A non-string "
        "session_id crashes `fleet status` and `status --json` with "
        "AttributeError: 'int' object has no attribute 'replace' at "
        "bin/fleet.py:140 -- `name_fs_stem`, reached from recompute via the "
        "outcomes path. That is a PATH-layer type confusion, not a render one: "
        "the same helper maps task files, outcomes, tombstones, journals, logs "
        "and archive dirs, and a mis-mapped stem WRITES to the wrong file. "
        "Deciding what it does with a non-string is a write-path decision this "
        "lane was not scoped for. strict=True so whoever fixes it is forced "
        "back here rather than leaving a stale xfail."))
    def test_a_non_string_session_id_does_not_crash_the_view(self, home):
        _write(home, {"w1": dict(_full(), session_id=7)})
        assert fleet.cmd_status(_args()) == 0

    def test_a_cost_the_coercer_refuses_renders_the_placeholder_not_the_number(
            self, home, capsys):
        """NaN and a negative are exactly what `_coerce_cost` exists to refuse.

        Printing `nan` or `-5.00` in the COST column asserts a measurement that
        the file's own coercer says is untrustworthy. That is the day-5 failure
        in miniature: a rendered lie is worse than a rendered `?`.
        """
        _write(home, {"nanny": dict(_full(), cost_usd=float("nan")),
                      "neggy": dict(_full(), cost_usd=-5.0)})
        assert fleet.cmd_status(_args()) == 0
        out = capsys.readouterr().out
        assert _column(out, "nanny", "COST") == UNKNOWN, out
        assert _column(out, "neggy", "COST") == UNKNOWN, out


# ---------------------------------------------------------------------------
# One bad row must not take the table down with it.
# ---------------------------------------------------------------------------

class TestOneBadRecordDoesNotSwallowTheOthers:

    def test_the_healthy_workers_either_side_still_render(self, home, capsys):
        """The observed harm was total, not partial: header, then nothing.

        Sorted order puts the broken record in the MIDDLE, so a fix that only
        stops the exception without continuing the loop is caught here.
        """
        _write(home, {"aaa": _full(),
                      "mmm": dict(FIXTURE_SHAPE),
                      "zzz": _full()})
        rc = fleet.cmd_status(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert set(_rows(out, ["aaa", "mmm", "zzz"])) == {"aaa", "mmm", "zzz"}, (
            f"one short record swallowed its neighbours -- rendered:\n{out}")

    def test_a_healthy_row_still_shows_its_real_numbers(self, home, capsys):
        """Non-vacuity: tolerance must not turn the whole table into `?`.

        A fix that renders every cell as the placeholder would satisfy every
        assertion above. This is what stops it.
        """
        _write(home, {"aaa": dict(_full(), turns=7, cost_usd=1.25),
                      "mmm": dict(FIXTURE_SHAPE)})
        assert fleet.cmd_status(_args()) == 0
        out = capsys.readouterr().out
        assert _column(out, "aaa", "TURNS") == "7", out
        assert _column(out, "aaa", "COST") == "1.25", out
        assert UNKNOWN not in _rows(out, ["aaa"])["aaa"], (
            "a fully-populated record must render no placeholder: "
            f"{_rows(out, ['aaa'])['aaa']!r}")


# ---------------------------------------------------------------------------
# The two renderers the brief named that are safe BY AN INVARIANT held
# elsewhere. Pin the invariant rather than sprinkle unreachable `.get`s.
# ---------------------------------------------------------------------------

class TestTheSnapshotRowContractTheOtherRenderersRestOn:
    """`_print_snapshot_table` (`:4191`) and `_render_boot_bundle` (`:11720`)
    direct-subscript their rows and cannot crash TODAY, because their single
    caller each feeds them `status_snapshot()` output, whose rows come from a
    dict literal. That is safety by an invariant nobody wrote down. Written
    down here: break the invariant and this reddens, instead of the crash
    resurfacing in a surface that had no pin.
    """

    # Every key those two functions subscript without a `.get`.
    REQUIRED = {"name", "status", "turns", "cost_usd", "mail", "stale_seconds",
                "resume_eligible", "dispatch_kind", "unknown_fields"}

    @pytest.mark.parametrize("field", BASELINE_FIELDS)
    def test_every_row_carries_the_keys_those_renderers_subscript(
            self, home, field):
        rec = _full()
        del rec[field]
        _write(home, {"w1": rec})
        for row in fleet.status_snapshot()["workers"]:
            missing = self.REQUIRED - set(row)
            assert not missing, (
                f"with {field!r} absent from the registry, status_snapshot "
                f"dropped {sorted(missing)} from its row -- "
                f"_print_snapshot_table/_render_boot_bundle subscript those.")

    @pytest.mark.parametrize("field", BASELINE_FIELDS)
    def test_the_totals_carry_a_formattable_cost(self, home, field):
        rec = _full()
        del rec[field]
        _write(home, {"w1": rec})
        totals = fleet.status_snapshot()["totals"]
        assert isinstance(totals["cost_usd"], float), (
            "_render_boot_bundle formats totals['cost_usd'] with :.2f")

    @pytest.mark.parametrize("field", BASELINE_FIELDS)
    def test_stale_seconds_is_always_none_or_a_number(self, home, field):
        """`_print_snapshot_table` divides it by 60. `_render_boot_bundle`'s
        neighbours read it too. `status_snapshot` derives it inside a
        try/except, so this holds -- written down because the age cell's guard
        rests on it."""
        rec = _full()
        del rec[field]
        _write(home, {"w1": rec})
        stale = fleet.status_snapshot()["workers"][0]["stale_seconds"]
        assert stale is None or (isinstance(stale, (int, float))
                                 and not isinstance(stale, bool)), repr(stale)

    def test_the_boot_bundle_renders_a_short_record(self, home):
        _write(home, {"w1": dict(FIXTURE_SHAPE)})
        text = fleet._render_boot_bundle([], fleet.status_snapshot(), [])
        assert "w1" in text

    def test_the_snapshot_table_survives_a_hand_built_row(self, home, capsys):
        """`_print_snapshot_table` is called directly, with hand-built rows, by
        tests in this repo (tests/test_terminal_surface.py builds one, so does
        tests/test_native.py) -- so "status_snapshot always fills these in" is
        not the whole story about what reaches it.

        Found by fault injection: the age cell's guard reddened nothing,
        because the only production producer can never emit a non-numeric
        `stale_seconds`. This is the input that does reach it.
        """
        snap = {"ok": True, "reason": None,
                "totals": {"workers": 1, "mail": 0, "cost_usd": 0.0,
                           "by_status": {}},
                "workers": [{"name": "w1", "status": "idle", "turns": 1,
                             "cost_usd": 0.5, "mail": 0,
                             "stale_seconds": "soon", "resume_eligible": False,
                             "dispatch_kind": None}]}
        fleet._print_snapshot_table(snap)          # must not raise
        out = capsys.readouterr().out
        assert _column(out, "w1", "AGE") == UNKNOWN, out
        # ...and a row with no `unknown_fields` at all still shows its numbers.
        assert _column(out, "w1", "COST") == "0.50", out
        assert _column(out, "w1", "TURNS") == "1", out


# ---------------------------------------------------------------------------
# One placeholder token, everywhere.
# ---------------------------------------------------------------------------

def test_the_two_tables_use_the_same_placeholder(home, capsys):
    """`?` in both, for the same record. Two views of one registry that
    disagree about how they spell "unknown" is the inconsistency the brief
    called out by name."""
    _write(home, {"w1": dict(FIXTURE_SHAPE)})
    assert fleet.cmd_status(_args()) == 0
    authoritative = capsys.readouterr().out
    assert fleet.cmd_status(_args(stale_ok=True)) == 0
    stale_ok = capsys.readouterr().out
    for label, out in (("fleet status", authoritative),
                       ("fleet status --stale-ok", stale_ok)):
        # The COST cell specifically. `--stale-ok` reads its cost through
        # `_registry_cost`, whose documented 0.0 fallback would otherwise
        # render a confident `0.00` for a cost that was never recorded --
        # the same record described two different ways by two views of it.
        assert _column(out, "w1", "COST") == UNKNOWN, (
            f"{label}: COST cell is not {UNKNOWN!r} for a record carrying no "
            f"cost_usd -- rendered:\n{out}")
        # Same for TURNS: `status_snapshot` defaults an absent turn count to 0,
        # which is the right answer for a consumer doing arithmetic and the
        # wrong one for a cell claiming this worker has taken no turns.
        assert _column(out, "w1", "TURNS") == UNKNOWN, (
            f"{label}: TURNS cell is not {UNKNOWN!r} for a record carrying no "
            f"turns -- rendered:\n{out}")
        assert "unknown" not in _rows(out, ["w1"])["w1"].lower(), (
            f"{label} used a SECOND spelling of the placeholder")
