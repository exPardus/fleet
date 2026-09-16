# w90 report — boot bundle measurement table and method

DONE means: the supervisor boot bundle is measured input-by-input in tokens, the largest inputs are cut so that a boot reads a capped checkpoint and pointers rather than whole journals, and the cap is pinned by a test that fails if the bundle grows past it.

## Method

Never read a transcript. Sections were measured by calling `_render_boot_bundle` and its
component pure functions directly against this worktree's own real, tracked
`supervisor/GOALS.md`, `supervisor/JOURNAL.md` and `knowledge/INDEX.md` (checked out at the
lane's base SHA, ab92bf1) — no `fleet sup-boot` invocation, so no lock, no write, no mutation
of this worktree's runtime state. Roster and registry were empty/absent in this worktree (a
lane worktree, not the live supervisor's `FLEET_HOME`); native-roster and fleet-status rows are
reported as a representative shape, not live counts, and are small by construction (the reap
rule already caps live workers at 3). Estimated tokens = `bytes / 4`, stated as a heuristic per
the lane's method rule — no tokenizer dependency was added. Script: measured inline via
`python3 -c` against `bin/fleet.py`'s functions (not committed; reproducible from the numbers
and commands below).

## Table — before this lane's cut (2026-09-16, this repo's real files)

| section | lines | bytes | ~tokens | % of bundle |
|---|---:|---:|---:|---:|
| `supervisor/GOALS.md` (whole file) | 133 | 7,056 | 1,764 | 57.5% |
| `supervisor/JOURNAL.md` tail (last 5, old: full bodies) | 16 | 3,526 | 882 | 28.7% |
| `knowledge/INDEX.md` (first 20 non-blank) | 12 | 854 | 214 | 7.0% |
| native roster line (1-line header) | 1 | 40 | 10 | 0.3% |
| fleet status (0 workers, this worktree) | 2 | 107 | 27 | 0.9% |
| computed board (git/pickup/lanes/directives/gates) | 13 | 521 | 130 | 4.2% |
| reap line + `SUPERVISOR_REAP_RULE` doctrine paragraph (outside the char-capped render) | 2 | 1,087 | 272 | n/a |
| **`_render_boot_bundle()` total (bundle only)** | 186 | **12,271** | **3,068** | 100% |

GOALS + journal tail = **86.2%** of the bundle — confirms the task brief's suspicion for the
journal tail, and (separately) identifies GOALS.md as the single largest section, larger than
the journal tail.

For scale: the live boot cited in the task brief (2026-09-16T12:40Z, 240-line bundle,
occupancy=60,946 tokens after the first checkpoint) is **not** this number — that occupancy
includes the harness system prompt, CLAUDE.md, the memory index and the wake brief, none of
which `sup-boot` assembles or this lane's scope covers. The ~3,068-token bundle measured here is
consistent with being a small fraction of that total, which is the point: decompose, don't quote.

## What grows without bound vs. what doesn't

- **`supervisor/JOURNAL.md` tail: bounded in ENTRY COUNT, not in BYTES.** `roll_supervisor_journal`
  (called by every `sup-checkpoint`) keeps only the newest 3 checkpoints on the board, and
  `SUPERVISOR_BODY_MAX_LINES` (3) caps a checkpoint body's *newline* count — but not the length of
  those three lines. Non-checkpoint kinds (`BOOT`, `SEIZED`, wave-close's `THROUGHPUT` line)
  append via `supervisor_journal_append` directly and carry no line cap at all. Confirmed by
  inspection, not assumption: this repo's own 2026-09-16T13:44 checkpoint is a 3-line body whose
  lines are each one long paragraph (measured at ~1,170 bytes for that one entry alone).
- **`supervisor/GOALS.md`: large (57.5% of the bundle) but NOT unboundedly growing.** It is
  operator-owned prose (spec §4: "Loaded first by every supervisor incarnation's boot ritual");
  its 133 lines have stayed roughly that size since 2026-07-14 per its own `## Status` section,
  bounded by editorial discipline rather than automatic accumulation. It is also the one section
  spec explicitly requires in full, every boot — not a journal, and not this lane's cut target.
  **Left uncut**, and reported here as the largest confirmed-but-not-cut input rather than
  silently ignored.

## The cut, and what a successor loses

`_render_boot_bundle`'s journal-tail block now inlines the body of only the **newest** of the
last `SUPERVISOR_BOOT_JOURNAL_TAIL` (5) entries; the older entries in the same window render as
one-line pointers (`## <ts> <KIND> inc=<inc> sid=<sid>` + `(body omitted -- pointer only; full
text: supervisor/JOURNAL.md)`). The newest entry's body is separately capped at
`SUPERVISOR_LATEST_ENTRY_MAX_CHARS` (2,000 chars) with a truncation pointer, as a backstop
`SUPERVISOR_BODY_MAX_LINES` does not provide (three lines can each be arbitrarily long).

A successor loses the PROSE of checkpoints 2-5 back from the newest — not their existence,
timestamp, kind, incarnation or session id, all of which stay in the pointer line. This is safe
because: (1) the newest entry's body is exactly the "what to do next" continuity note the
operator/supervisor writes for a resuming body (see this repo's own 2026-09-16T13:44 entry:
"Next: item 3, handoff cost." — that is what a boot actually needs); (2) older bodies are one
`cat supervisor/JOURNAL.md` (or `supervisor/journal-history/*.md` once rolled) away and rarely
needed at boot, only during deep incident review; (3) `roll_supervisor_journal` already treats
entries older than the newest 3 checkpoints as history, not live state — this cut narrows the
same "history vs. live" line one step further, from "3 checkpoints with bodies" to "1 checkpoint
with a body, 2-4 as pointers."

Not cut: `VERDICT`/`INCARNATION`/`NONCE` lines, the `EPOCH` line, and the reap/doctrine trailer —
none are journal content, and the continuity proof is explicitly out of scope for cutting.

## Table — after this lane's cut

| section | bytes | ~tokens |
|---|---:|---:|
| `supervisor/JOURNAL.md` tail — OLD (5 full bodies) | 3,526 | 882 |
| `supervisor/JOURNAL.md` tail — NEW (1 body + 4 pointers) | 1,720 | 430 |
| **`_render_boot_bundle()` total — OLD** | **12,271** | **3,068** |
| **`_render_boot_bundle()` total — NEW** | **10,349** | **2,587** |
| saved | 1,922 | 480 (15.7%) |

15.7% off the assembled bundle on this repo's *current* journal (4 entries, none pathological).
The cut's real payoff is the ceiling it removes, not this one measurement: before it, a single
large checkpoint or a wave-close `THROUGHPUT` line could make the tail arbitrarily large with no
code-level limit; after it, only the newest entry can grow the tail, and it is byte-capped.

## The cap

`SUPERVISOR_BUNDLE_MAX_CHARS` already existed (40,000 chars) as a whole-bundle backstop
(`_render_boot_bundle` raises `FleetCliError` past it) but **no test exercised it** — grep
confirmed zero references anywhere in `tests/` before this lane. Lowered to **20,000** chars
(~5,000 tokens): roughly 2x the measured post-cut bundle (10,349 bytes) with 0 live workers,
enough headroom for GOALS.md to grow moderately or for a full 3-worker roster (the reap rule's
own ceiling) without the cap being effectively unbounded, and well below the untested 40,000
predecessor whose slack nobody had measured. **Today's real bundle does not violate either the
old or the new cap** — the useful finding here is the missing test, not a status-quo violation.
Pinned by `tests/test_boot_bundle_cost.py::TestBundleByteBudget` (both arms: realistic content
stays under budget, and a synthetically oversized bundle is refused).

## Commands

```
uv run --no-project --python 3.10 --with pytest python -m pytest -q tests/test_boot_bundle_cost.py
uv run --no-project --python 3.12 --with pytest python -m pytest -q tests/test_boot_bundle_cost.py
```
