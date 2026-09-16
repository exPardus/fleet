"""w90: what `sup-boot` assembles is re-read by every later turn of that
incarnation through cache_read, so a line cut at boot is cut many times over
(docs/lanes/w90.md). MEASURED (this repo's own supervisor/GOALS.md +
JOURNAL.md + knowledge/INDEX.md, 2026-09-16): GOALS.md is 7,056 bytes (57% of
the rendered bundle) and the old "last 5 full checkpoints" journal tail was
3,526 bytes (29%) -- together 86%. GOALS.md is operator-owned, bounded by
editorial discipline and explicitly required in full every boot (spec §4);
the journal tail was not bounded in BYTES at all -- `SUPERVISOR_BODY_MAX_LINES`
caps a checkpoint's newline count (3), not the length of those three lines,
and non-checkpoint kinds (BOOT/SEIZED/wave-close THROUGHPUT) go through
`supervisor_journal_append` directly and carry no line cap either.

THE CUT, v2 (supervisor gate, 2026-09-16, rejecting v1's "inline only the
newest entry"): the inline slot is spent on CONTENT, not on whichever entry
happens to be newest. `SUPERVISOR_JOURNAL_SUBSTANTIVE_KINDS` (CHECKPOINT,
PROPOSAL) are eligible to inline; terse bookkeeping kinds (BOOT/SEIZED/...)
are ALWAYS pointers, regardless of position -- counter-evidence was this
repo's own 2026-09-16T12:40Z boot, whose newest tail entry was the BOOT the
boot itself had just written (one line, zero campaign content); v1 would
have pointered the checkpoints behind it, including the ones the supervisor
brief's step 4 ("continue the campaign from the journal tail") needs inline.
At least `SUPERVISOR_BOOT_INLINE_MIN` (2) substantive entries inline
newest-first when that many exist; more inline while the cumulative
per-entry-capped size stays within `SUPERVISOR_JOURNAL_INLINE_BUDGET_CHARS`.
Each inlined entry is still byte-capped at `SUPERVISOR_LATEST_ENTRY_MAX_CHARS`
as a backstop `SUPERVISOR_BODY_MAX_LINES` (newline count, not byte length)
does not provide. `SUPERVISOR_BUNDLE_MAX_CHARS` (whole-bundle backstop) drops
from an untested 40,000 to a measured, justified 20,000 -- see the
constants' comments in bin/fleet.py for the arithmetic. Both caps are
unchanged from v1 per the gate.
"""
from pathlib import Path

import pytest

import fleet


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with a GOALS.md and a seeded knowledge index."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n",
                                  encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text(
        "# Knowledge Index\n- entry one\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    return tmp_path


def _append(kind, inc, sid, body):
    fleet.supervisor_journal_append(kind, inc, sid, body)


def _bundle(snap=None):
    snap = snap or {"ok": True, "totals": {"workers": 0, "cost_usd": 0.0, "mail": 0},
                    "workers": []}
    return fleet._render_boot_bundle(
        [], snap, fleet.supervisor_journal_entries(), caller_sid=None)


class TestSelectBootJournalInlineIndices:
    """The pure selector, exercised directly against the real 2026-09-16 tail
    shape the supervisor gate cited: a BOOT entry newest, CHECKPOINTs behind
    it. Also covered end-to-end through `_render_boot_bundle` below."""

    def _tail(self, kinds):
        return [{"ts": f"t{i}", "kind": k, "inc": "inc-1", "sid": "s1", "body": f"B{i}"}
                for i, k in enumerate(kinds)]

    def test_a_newest_boot_entry_does_not_crowd_out_checkpoints_behind_it(self):
        # supervisor gate's own counter-example, 2026-09-16T12:40Z boot.
        tail = self._tail(["CHECKPOINT", "CHECKPOINT", "BOOT"])
        idx = fleet._select_boot_journal_inline_indices(tail)
        assert idx == {0, 1}

    def test_a_solitary_bookkeeping_entry_is_never_inlined(self):
        tail = self._tail(["BOOT"])
        assert fleet._select_boot_journal_inline_indices(tail) == set()

    def test_bookkeeping_kinds_never_count_toward_the_minimum(self):
        tail = self._tail(["CHECKPOINT", "SEIZED", "RELEASED", "BOOT"])
        idx = fleet._select_boot_journal_inline_indices(tail)
        assert idx == {0}  # only one substantive entry exists -- inline what there is

    def test_at_least_the_minimum_inlines_even_with_only_that_many_available(self):
        tail = self._tail(["PROPOSAL", "CHECKPOINT"])
        idx = fleet._select_boot_journal_inline_indices(tail)
        assert idx == {0, 1}


class TestBookkeepingKindsAreAlwaysPointersInTheBundle:
    def test_a_newest_boot_entry_is_a_pointer_even_though_it_is_newest(self, sup_home):
        _append("CHECKPOINT", "inc-1", "sid-1", "OLD-CAMPAIGN-STATE")
        _append("CHECKPOINT", "inc-1", "sid-1", "NEW-CAMPAIGN-STATE")
        _append("BOOT", "inc-1", "sid-1", "resumed own claim -- continuity proved")
        bundle = _bundle()
        assert "OLD-CAMPAIGN-STATE" in bundle
        assert "NEW-CAMPAIGN-STATE" in bundle
        assert "resumed own claim -- continuity proved" not in bundle
        assert "full text: supervisor/JOURNAL.md" in bundle

    def test_a_solitary_bookkeeping_journal_is_pointered_not_inlined(self, sup_home):
        _append("BOOT", "inc-1", "sid-1", "ONLY-ENTRY-BODY")
        bundle = _bundle()
        assert "ONLY-ENTRY-BODY" not in bundle
        assert "full text: supervisor/JOURNAL.md" in bundle

    def test_no_checkpoints_yet_is_unchanged(self, sup_home):
        assert "(no checkpoints yet)" in _bundle()


class TestSubstantiveEntriesInlineNewestFirstUpToBudget:
    def test_two_small_checkpoints_both_inline(self, sup_home):
        _append("CHECKPOINT", "inc-1", "sid-1", "FIRST-BODY")
        _append("CHECKPOINT", "inc-1", "sid-1", "SECOND-BODY")
        bundle = _bundle()
        assert "FIRST-BODY" in bundle and "SECOND-BODY" in bundle
        assert "full text: supervisor/JOURNAL.md" not in bundle

    def test_the_oldest_eligible_entry_pointers_once_the_budget_is_exceeded(self, sup_home):
        # 5 entries at the per-entry cap: budget (4x cap) covers exactly 4 of
        # them, so the oldest of the five substantive entries is a pointer.
        near_cap = "Y" * (fleet.SUPERVISOR_LATEST_ENTRY_MAX_CHARS + 1)
        for i in range(5):
            _append("CHECKPOINT", "inc-1", "sid-1", f"MARK{i}-{near_cap}")
        bundle = _bundle()
        for i in range(1, 5):
            assert f"MARK{i}-" in bundle, f"entry {i} should still be inlined"
        assert "MARK0-" not in bundle, "oldest of 5 near-cap entries should pointer"
        assert "full text: supervisor/JOURNAL.md" in bundle

    def test_only_the_last_N_entries_enter_the_window_at_all(self, sup_home):
        """Entries older than the tail window are absent altogether, pointer
        or not -- the window size is unchanged by this cut."""
        for i in range(8):
            _append("CHECKPOINT", "inc-1", "sid-1", f"E{i}")
        bundle = _bundle()
        # window is the newest SUPERVISOR_BOOT_JOURNAL_TAIL entries: E3..E7
        for i in range(3):
            assert f"E{i}\n" not in bundle and f"E{i} " not in bundle
        assert "E7" in bundle  # newest, small enough to fit the budget


class TestInlinedEntriesAreByteCapped:
    def test_an_oversized_body_is_truncated_with_a_pointer(self, sup_home):
        huge = "X" * (fleet.SUPERVISOR_LATEST_ENTRY_MAX_CHARS + 500)
        _append("CHECKPOINT", "inc-1", "sid-1", huge)
        bundle = _bundle()
        assert huge not in bundle
        assert "X" * fleet.SUPERVISOR_LATEST_ENTRY_MAX_CHARS in bundle
        assert "truncated 500 chars" in bundle
        assert "full text: supervisor/JOURNAL.md" in bundle

    def test_a_body_within_budget_is_not_touched(self, sup_home):
        body = "short and unremarkable"
        _append("CHECKPOINT", "inc-1", "sid-1", body)
        bundle = _bundle()
        assert bundle.count(body) == 1
        assert "truncated" not in bundle


class TestBundleByteBudget:
    """The whole-bundle backstop (`SUPERVISOR_BUNDLE_MAX_CHARS`): a cap that
    is never exercised by a test is not a pin, it is a comment. Both arms
    (comfortably under budget; well over budget raises) are covered."""

    def test_realistic_content_stays_comfortably_under_budget(self, sup_home):
        goals = "\n".join(f"policy line {i}" for i in range(140))
        (sup_home / "supervisor" / "GOALS.md").write_text(goals, encoding="utf-8")
        for i in range(5):
            _append("CHECKPOINT", "inc-1", "sid-1",
                   f"checkpoint body {i}, a normal paragraph of working notes.")
        bundle = _bundle()
        assert len(bundle) < fleet.SUPERVISOR_BUNDLE_MAX_CHARS

    def test_an_oversized_bundle_is_refused(self, sup_home):
        (sup_home / "supervisor" / "GOALS.md").write_text(
            "X" * (fleet.SUPERVISOR_BUNDLE_MAX_CHARS + 1000), encoding="utf-8")
        with pytest.raises(fleet.FleetCliError, match="exceeds"):
            _bundle()

    def test_the_cap_was_lowered_from_the_untested_predecessor(self):
        # w90: 40,000 chars was never exercised by any test (grep confirmed
        # empty before this file). The number itself must stay a measured,
        # justified choice, not silently regress back upward.
        assert fleet.SUPERVISOR_BUNDLE_MAX_CHARS == 20_000
