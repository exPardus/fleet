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

**v1 (rejected by the supervisor gate, 2026-09-16):** inline only the single newest tail entry.
Counter-evidence was this repo's own 2026-09-16T12:40Z boot: the newest tail entry at that boot
was the `BOOT` entry the boot itself had just written — one line, zero campaign content. v1 would
have spent the one inline slot on it and pointered the checkpoints behind it, including the
`PARKED` checkpoint and the w86 token-efficiency checkpoints that carried the actual campaign
state — directly breaking the supervisor brief's step 4, "continue the campaign from the journal
tail." Rejected: trading that for ~480 tokens (0.06% of w87's 849,667-token handoff) is a bad,
asymmetric trade — a successor that has to re-derive campaign state pays thousands of tokens to
recover hundreds.

**v2 (current):** the inline slot is spent on CONTENT, not on whichever entry is newest.
`_select_boot_journal_inline_indices` inlines bodies only for `SUPERVISOR_JOURNAL_SUBSTANTIVE_KINDS`
(`CHECKPOINT`, `PROPOSAL`) — the kinds that carry campaign content — never for terse bookkeeping
kinds (`BOOT`, `SEIZED`, `RELEASED`, ...), regardless of position. Walking newest-first, at least
`SUPERVISOR_BOOT_INLINE_MIN` (2) substantive entries inline when that many exist; more inline
while the cumulative per-entry-capped size stays within `SUPERVISOR_JOURNAL_INLINE_BUDGET_CHARS`
(4x the per-entry cap = 8,000 chars — a 5-entry window holds at most 5 substantive entries, so
this bounds the section to roughly "2 guaranteed, up to 2 more if they fit" rather than
"everything," leaving headroom under the 20,000 whole-bundle cap alongside GOALS.md's measured
7,056 bytes). Each inlined entry is still capped at `SUPERVISOR_LATEST_ENTRY_MAX_CHARS` (2,000
chars) with a truncation pointer, unchanged from v1.

A successor loses the PROSE only of substantive entries older than the inline budget covers, and
of terse bookkeeping entries always — never their existence, timestamp, kind, incarnation or
session id, all of which stay in the pointer line. Re-run against this repo's own real tail
(CHECKPOINT, BOOT, CHECKPOINT, CHECKPOINT): the BOOT entry pointers even though it is newest, and
all three CHECKPOINT bodies — including the wave-83 campaign summary — inline.

Not cut: `VERDICT`/`INCARNATION`/`NONCE` lines, the `EPOCH` line, and the reap/doctrine trailer —
none are journal content, and the continuity proof is explicitly out of scope for cutting.

## Table — after this lane's cut (v2)

The journal-tail section depends only on `supervisor/GOALS.md`/`JOURNAL.md` content and the
selection constants, all fixed for this measurement, so it reproduces exactly. The *total* bundle
additionally includes `_supervisor_git_board`'s live `dirty=<N>` count for this worktree, which
changes turn to turn as files are edited — reported here as one snapshot, not a reproducible
figure; the deterministic tail-section number is the one to trust.

| section | bytes | ~tokens |
|---|---:|---:|
| `supervisor/JOURNAL.md` tail — pre-w90 (5 full bodies, no kind-awareness) | 3,526 | 882 |
| `supervisor/JOURNAL.md` tail — v2 (3 CHECKPOINT bodies inline, 1 BOOT pointer) | 3,640 | 910 |
| **`_render_boot_bundle()` total — pre-w90** | **12,271** | **3,068** |
| **`_render_boot_bundle()` total — v2 (one snapshot; git-board-dependent, ±~100)** | **≈12,270-12,340** | **≈3,070-3,085** |

On *this repo's current, non-pathological* tail (only one terse entry, three real checkpoints),
v2's tail section costs slightly *more* than the naive pre-w90 whole-tail render (+114 bytes, the
pointer line's overhead) — that is the correct, expected result of the supervisor gate's
correction: this cut's value was never about shrinking today's ordinary tail, it is the CEILING it
removes. Before it, a tail dominated by bookkeeping churn (repeated BOOT/SEIZED cycles) or a single
pathologically large checkpoint had no code-level bound; after it, terse kinds never consume the
inline budget and every inlined body is still byte-capped.

## The cap

`SUPERVISOR_BUNDLE_MAX_CHARS` already existed (40,000 chars) as a whole-bundle backstop
(`_render_boot_bundle` raises `FleetCliError` past it) but **no test exercised it** — grep
confirmed zero references anywhere in `tests/` before this lane. Lowered to **20,000** chars
(~5,000 tokens): roughly 1.6x the measured v2 bundle (≈12.3KB) with 0 live workers, enough
headroom for GOALS.md to grow moderately or for a full 3-worker roster (the reap rule's own
ceiling) without the cap being effectively unbounded, and well below the untested 40,000
predecessor whose slack nobody had measured. **Today's real bundle does not violate either the
old or the new cap** — the useful finding here is the missing test, not a status-quo violation.
Kept exactly as-is across the v1→v2 correction (supervisor gate, 2026-09-16): only the inline
*selection rule* changed, not either cap's value. Pinned by
`tests/test_boot_bundle_cost.py::TestBundleByteBudget` (both arms: realistic content stays under
budget, and a synthetically oversized bundle is refused).

## Commands

```
uv run --no-project --python 3.10 --with pytest python -m pytest -q tests/test_boot_bundle_cost.py
uv run --no-project --python 3.12 --with pytest python -m pytest -q tests/test_boot_bundle_cost.py
```
