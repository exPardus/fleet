# Multi-fleet slice a — a price, not an implementation

Wave 41, lane `w41-mf` (worktree `C:\proga\fleet-w41-mf`, branch `w41/mf-slice-a`, forked from
main at `28df49b`). This document is evidence for a build-dispatch decision. It is not under
`docs/specs/`, deliberately — see the naming note below — so nothing in it is a
`tools/verify_receipts.py` receipt; command output pasted here is illustrative, not pinned to a
commit, and will not be re-executed. **No production code was written to produce this price.**
`bin/fleet.py` and every other shipped file are untouched on this branch (`git status` clean,
`git diff main` empty except this file and the journal).

## 0. Naming: "slice a" is correct, and slice 0 is already built

The brief's "slice a" and the spec's own vocabulary agree — no discrepancy to report here.
`docs/specs/multi-fleet.md` Sequencing §3 enumerates disjoint slices `0, a, b, c, d, e`. Slice 0
(the install/home split) **already landed** — commits `94a549b` (feat, +736/-71 across 10 files)
and `176c6b4` (test, +418/-1 across 3 files), both dated 2026-07-31, both referenced in the
spec's own "Slice 0" section under a `**BUILT 2026-07-31**` heading. So the *first slice still to
be priced/built* is `(a)`, matching the brief's guess exactly. Sequencing §3 item (a), quoted
verbatim: *"`read_registry_at` + list + lookup + arming + verb-effect table + `fleet homes` +
global flag (with the rb7 C-2 argparse pin)."*

**Filename note.** No `docs/specs/*price*.md` or `docs/specs/*evidence*.md` convention exists in
this repo. Estimate/evidence documents that are not themselves specs live directly under `docs/`
(precedent: `docs/mf-oracle-m1-evidence.md`), while `docs/reviews/` holds adversarial-gate and
adjudication output. A price is neither a spec nor a gate verdict, and — load-bearingly — a price
document that pastes command output would become a receipt if placed under `docs/specs/`,
binding it to a commit forever for a number that is supposed to change as the build proceeds.
So this lands at `docs/mf-slice-a-price.md`, following the `docs/mf-*-evidence.md` precedent
rather than inventing a `docs/specs/` name.

## 1. Is the document currently buildable? Yes — wave 34's finding is resolved

Wave 34 found this exact document ratified in the operator docket while its own `Status:` line
still read `AWAITING OPERATOR RULING` and Sequencing item 2 still blocked dispatch — "a
ratification lands in as many documents as name it, and this one did not fully land"
(`knowledge/INDEX.md`, 2026-07-31 entry). Re-checked now, fresh, by reading the two places that
mattered:

- **`Status:` line** (multi-fleet.md:3-4): *"v8 — ratified ready-for-build by Altai 2026-07-30"*,
  with the ruling transcribed verbatim into the document, matching
  `docs/OPERATOR-GATES.md:26` word for word.
- **Sequencing §§1-3** (multi-fleet.md:293-318): item 1 = gate rounds complete (historical).
  Item 2 explicitly states *"DISCHARGED 2026-07-30"* and quotes the ruling that lifted its own
  former blocking clause: *"the block this item used to state ('No build slice dispatches
  before the operator rules') is discharged and step 3 is open."* Item 3 lists the slices,
  slice 0 marked done in its own section above, and does not itself carry any blocking language.

Nothing in the document contradicts the ratification anymore. The commit that fixed this is
`09995f9` ("land the 2026-07-30 ratification on the spec"), which predates slice 0. **The
document reads as buildable today.** This is a re-derivation, not an inherited claim — I read
the live lines above rather than trusting the wave-34 finding or the brief's framing of it.

## 2. Scope, enumerated from the spec

Everything below is what slice (a) must deliver, by the Sequencing §3(a) list, cross-referenced
to the sections that define each term:

| # | Deliverable | Spec anchor | What it means concretely |
|---|---|---|---|
| 1 | `read_registry_at` | §5 step 2, §8 item, M1 scope | A path-parameterized, lock-free, tolerant registry reader. M1's own text: *"the tolerant path-parameterized reader is NEW work"* — corrects v6's "zero raises" claim, which was driven on a round-3 **prototype**; must be built to the driven contract with **the prototype's 12 corruption shapes as a RED-first fixture set**. |
| 2 | the homes list | §4 | `~/.claude/fleet-homes.list`: append-only writer (`atomic_append_bytes`), tolerant multi-encoding decode, sequence-fold membership (`add·retire·add` = member), absolute-path grammar (drive-letter/UNC/leading-`/`, never `os.path.isabs`), invalid lines never invalidate others, unreadable list ⇒ armed-with-unknown-population. |
| 3 | lookup | §5 step 2 | sid→home resolution over the folded homes-list population: per-home `read_registry_at` snapshot, tri-state hit/miss/unreadable, membership = per-record `session_id` ∪ `retired_sids` (never `spawned_by`), exactly-one-hit resolves, two-plus refuses naming all, miss falls through for every verb class. |
| 4 | arming | §5 "Arming" paragraph | Armed when the population holds ≥2 distinct homes counting valid AND unreadable; **any indeterminate population state arms** (never the permissive branch); <2 determinate ⇒ byte-identical to today. |
| 5 | verb-effect table | §5 table + guard paragraph | Three-tier classification (destructive / disruptive / ordinary) of shipped verbs by worst wrong-home effect, plus the guard: destructive via env/legacy requires `--yes` + witness; disruptive via env/legacy proceeds but renders provenance; ordinary flows; lookup-hit resolutions are exempt from both tiers. |
| 6 | `fleet homes` | M1 scope, §4 | New verb: view / `--add` / `--retire`. Not yet built — `RATIFIED_BUT_UNBUILT = ("homes",)` in `tests/test_round7_defect_pins.py:264` records this explicitly. |
| 7 | global `--fleet-home` flag | §5 step 1, M1 "binding slice constraint" | Applied in `main()` before dispatch; validation = resolve + `is_dir` + initialized, no side-effect `mkdir`; flag/lookup disagreement ⇒ mutating verbs refuse without `--yes` + witness. Binding constraint (both round-5 lenses): **ships in or before the arming slice** — since arming is itself item 4 of this same slice, the flag cannot be later than (a). |
| 8 | rb7 C-2 argparse pin | §5 "Shipped-defect slice condition" + its correction | The global-flag promotion must not let a subparser silently clobber the global dest. Already lint-gated by `tests/test_round7_defect_pins.py::TestGlobalPositionFleetHome` (5 tests, landed in slice 0) — **currently passing vacuously** because no global flag exists yet to collide. Slice (a) is the first slice where this assertion does real work. |

**Two operator-ruled residuals bind this slice's behaviour, not just its shape** (quoted from
`docs/OPERATOR-GATES.md:26`): the pre-claim window (6.8–63s, accepted, not to be "fixed") and
"wrong-home disruptive verbs proceed loudly rather than refuse" (item 5's disruptive row is not
negotiable — do not tighten it to a refusal during implementation).

### Ambiguities found (cheaper now than mid-build)

1. **§7's test-isolation pins — does slice (a) own them, or does slice (e)?** §7 lists ten pin
   categories (env fixture, homes-list-path monkeypatch, real-list-untouched pin, quiescent-home
   canary, membership+fold pins, writer-contention pin, no-rewrite lint, rendered
   "not initialized", the destructive-tier pin, the arming-indeterminacy pin) and is headed
   "Unchanged from v6" as though it already exists — it does not (verified: zero matches for
   `fleet-homes.list`, `armed`/`arming` used only by the *unrelated* claim-nonce supervisor gate
   in `tests/test_gate_arm_wedge.py` / `test_supervisor_gate.py`). Sequencing §3 lists `(e) pins`
   as its own slice, separate from `(a)`'s list — which reads as "§7's full catalog is slice
   (e)'s deliverable." But the Sequencing intro also states every slice gates
   "RED-then-GREEN both floors serially," and you cannot RED→GREEN a destructive tier or an
   arming rule without a test that exercises it — you cannot defer *all* verification of (a)'s
   own features to a slice that ships after (b)/(c)/(d). **Reading taken for this price:** (a)
   ships functional tests for everything it builds (as any RED-then-GREEN slice must), including
   the two §7 pins that verify (a)'s own surface directly — the destructive-tier pin and the
   arming-indeterminacy pin — while the remaining §7 items that presuppose later slices' plumbing
   (hook argv, statusline capture-gating) genuinely wait for (e). This reading is priced below;
   if the operator intends the opposite (defer all of §7 to (e), (a) ships with only ad hoc unit
   tests), the estimate in §5 shrinks by roughly the "§7 pins" test-writing line in the table.
2. **Is `homes --add`/`--retire` itself subject to the verb-effect guard?** §5's table classifies
   `homes --add/--retire` as "ordinary (list-reversible)" — but this classification appears in
   the verb-effect table prose, not in the `RATIFIED_ORDINARY` tuple pinned by
   `tests/test_round7_defect_pins.py:260` (which only lists `spawn, init, status, peek, result`).
   Building `fleet homes` without updating that pin's tuple will make an existing test wrong
   silently (it currently passes only because `homes` doesn't exist yet — see
   `RATIFIED_BUT_UNBUILT`). Not a hard blocker, just a coupled edit slice (a) must remember: the
   pin file and the spec table must move together.
3. **`read_registry_at`'s 12 corruption shapes are not transcribed anywhere in this repo's
   tracked files** — they are referenced only as "the round-3 prototype's" fixture set. The
   actual list lives in `C:/proga/claude-fleet/state/journals/REPORT-mf-rs6.md` /
   `REPORT-mf-rs7.md` (round-6/7 lens reports, outside this repo, in the fleet manager's own
   state directory), and even those reports don't enumerate all twelve — they only confirm the
   *count* and document two shapes the sweep *missed* (recursion-bomb, oversize document; see
   Risk 1 below). Whoever builds (a) needs to either locate the original round-3 prototype's
   fixture list or re-derive twelve shapes from scratch and say so.

## 3. File-level blast radius (derived from the tree, not the spec's prose)

**Production:** `bin/fleet.py` only. It is single-file stdlib-only, currently **19,693 lines**,
32 shipped subparsers (verified by introspecting `fleet.build_parser()` directly, not by
counting `add_parser(` calls in the source — that overcounts nested `sup-*` sub-subparsers).
There is no second production file this slice plausibly touches: hooks
(`bin/hooks/*.py`, 940 combined lines) and `worker-settings.template.json` are slice (c)'s;
`bin/fleet_statusline.py` is slice (d)'s.

Concretely, within `bin/fleet.py`, slice (a) adds:
- One new tolerant reader function (`read_registry_at`) — sized like its existing sibling
  `_read_registry_readonly` (`:3834-3878`+, ~45 lines, of which roughly two-thirds is doctrine
  docstring in this file's own convention — expect the same ratio here, not less).
- A homes-list I/O module: reader (tolerant decode, fold) + writer (`atomic_append_bytes`
  already exists as a precedent adapter at two call sites, `:392`/`:453` per `REPORT-mf-rs7.md`
  P-4 — reused, not reinvented).
- Resolution-order wiring in `main()` (a new function implementing §5's 5-step order, plus one
  new global argument on the top-level parser — today the top-level parser has **zero** options
  besides `-h/--help`, confirmed by direct introspection).
- Arming + the verb-effect table as data (three tuples or equivalent) plus one guard function.
- **Guard integration at roughly 11 existing call sites** — every verb in the ratified
  destructive (`clean`, `archive`, `autoclean`, `doctor --repair`, `sup-handoff-abort`) and
  disruptive (`kill`, `interrupt`, `send`, `respawn`, `release`) rows, none of which currently
  call anything resembling a wrong-home guard (`_confirm_destructive`, the only related
  existing guard, is an *ownership* check with disjoint call sites from what this list needs —
  confirmed disjoint by `tests/test_round7_defect_pins.py`'s own docstring, rs7 C-3).
- One new subparser (`homes`) with `--add`/`--retire`, i.e. verb 33.

Compare to the two precedent commits actually measured on this branch's own history:

```
94a549b (slice 0, feat)        10 files,  736 insertions(+), 71 deletions(-)
176c6b4 (round-7 pins, test)    3 files,  418 insertions(+),  1 deletion(-)
```

Slice 0 was a **repoint of 8 already-named symbols** to a second root — mechanical, low
ambiguity, one new large test file. Slice (a) is qualitatively different: it designs and lands
three new subsystems (a tolerant reader, an append-only list format, a resolution/arming
algorithm) *and* disperses a guard across ~11 pre-existing call sites in a 19.7k-line file, each
of which needs "re-grep before touching" (this file's own house rule, stated in the slice-0
section for exactly this reason) rather than a blind edit from a spec-quoted line number. Dispersed
edits are the more expensive kind here — this repo's own measurement doctrine says a merge's
cost is "what moved," not diff size (`docs/NEXT-SESSION.md`'s Measurement Doctrine section), and
"moved" for this slice means eleven separate existing functions each acquiring a new early-exit
branch, not one new block of code.

**Test files**, by the same derivation method (grep, not estimation): zero existing test files
reference `fleet-homes.list`, `read_registry_at`, or multi-fleet's arming/verb-effect concept —
the only `armed`/`arming` hits in `tests/` (`test_gate_arm_wedge.py`, `test_supervisor_gate.py`,
`test_doctor_claim_provenance.py`, `test_b6_sid_union.py`, `test_identity_*`,
`test_sup_release_tombstone.py`, `test_steer*.py`, `test_status_render_tolerance.py`,
`test_unlocked_quarantine.py`, `test_views_doctrine.py`, plus the two round-7/install-split
files) belong to the **unrelated, already-shipped** claim-nonce supervisor-claim gate. Slice (a)
is building its homes/arming test surface from zero, in new file(s) — expect at least:
`test_homes_list.py` (§4's format + fold + append-only + tolerant decode),
`test_home_resolution.py` (§5's 5-step order + terminus), `test_verb_effect_arming.py`
(the table, the guard, the two §7 pins from ambiguity #1), plus fixture additions to
`test_round7_defect_pins.py` (the argparse pin must flip from vacuous to load-bearing without
going red) and a `**BUILT**`-style correction section appended to `docs/specs/multi-fleet.md`
itself (slice 0's was +37 lines in the feat commit, +14 more in the pin commit — 51 lines total
of dense corrective prose; expect similar or more, since (a) has more moving parts to report on
than (0) did).

## 4. Test surface — what must be pinned, and which round-7 pins are live

**Of the two round-7 defect pins the operator named as slice conditions, only one is still
slice (a)'s to satisfy:**

- **rb7 C-2 (the argparse clobber) — LIVE, squarely slice (a)'s.** The lint
  (`tests/test_round7_defect_pins.py::TestGlobalPositionFleetHome::test_no_subparser_redefines_a_top_level_dest`)
  already exists and currently passes only because there is nothing to collide (no global flag
  yet). Its own seed test (`test_the_seed_the_collision_detector_can_see_a_collision`) is what
  proves the detector isn't dead code. Slice (a) must promote `--fleet-home` to a global flag
  **while keeping this lint green** — which per the file's own prescription (its docstring,
  quoted: *"reconcile the dests, never let the global value survive by luck of position"*) means
  sharing one parser object or renaming `autoclean`'s local dest, not picking a winning
  argv position.
- **rb7 C-3 (`doctor --repair` absent from every destructive enumeration) — ALREADY
  DISCHARGED, in slice 0.** `tests/test_round7_defect_pins.py`'s own module docstring (B2
  section) records this: the flag was already present in the ratified table and in
  `test_view_quarantine.py`'s two guards; the one genuine gap
  (`tests/test_terminal_surface.py::TestCommandFiles.DESTRUCTIVE_VERBS`, plus three siblings —
  `archive`, `autoclean`, `sup-handoff-abort` — that a narrower fix would have missed) was
  closed in the same commit as the pin file (`176c6b4`). **This is not owed by slice (a).**
  Restating it as an open slice-a obligation (as a shallow reading of the brief's phrasing might)
  would be a wasted line item.

**New pins slice (a) must land** (beyond the functional tests in §3): the destructive-tier pin
(armed machine, env-resolved `clean` refuses naming the flag; env-resolved `spawn` proceeds) and
the arming-indeterminacy pin (unreadable list arms; the `<2` baseline stays byte-identical to
today) — per Ambiguity #1's reading, both verify surface slice (a) itself builds and so cannot
reasonably wait for slice (e). The remaining §7 items (quiescent-home canary, writer-contention,
no-rewrite lint, "rendered not initialized") verify §4's homes-list mechanics directly and
belong with deliverable #2 in the scope table above, not with slice (e) — they are pins on
*this* slice's own list-format work, not on later slices' plumbing.

**RED-then-GREEN, both floors, per the Sequencing intro's own rule** — `py -3.13` and
`py -3.10`, matching every prior slice's discipline (slice 0's commit message: "RED watched on
both floors ... then GREEN. Full suite 3559/14/1 on py 3.13 AND py 3.10"). Current baseline on
this branch: **3662 tests collected** (`py -3.13 -m pytest -q --collect-only`, run on this
worktree, uncommitted work). Any slice-(a) landing needs to re-run this baseline fresh rather
than inherit it — this repo's own doctrine (`docs/NEXT-SESSION.md`: "STATE — RE-MEASURE, never
inherit") applies here as much as anywhere.

## 5. Context-cost estimate against the 150–200k band

Anchors this repo has already measured (`knowledge/lessons.md:147`, wave-30 interface stress
test): **a `bin/fleet.py` merge runs ~60–65k tokens; a docs-only merge ~35k.** Those numbers were
earned on *concentrated* changes (one feature, one place). Slice (a) is the opposite shape — see
§3 — so pricing it as one `bin/fleet.py` merge understates it.

**Slice (a) as specified does not fit in one worker's 150–200k band. Recommend splitting into
three dependency-ordered sub-slices**, each independently RED→GREEN-able (matching this
project's own per-slice gating doctrine) and each small enough to land inside the band:

| Sub-slice | Contents | Why this boundary | Rough cost |
|---|---|---|---|
| **a1 — the data layer** | `read_registry_at` (+ 12-shape fixture set, Risk 1 below), the homes-list reader/writer (§4), `fleet homes` verb (view/`--add`/`--retire`) | Self-contained: no existing call site depends on it yet. Testable in total isolation. Closest in shape to slice 0's own "repoint N named symbols," but with more net-new logic (a new file format, not a re-point) | ~70–90k |
| **a2 — resolution + the flag** | §5's 5-step order wired into `main()`, the global `--fleet-home` flag, the rb7 C-2 dest reconciliation | Depends on a1's reader/list existing. Small in code, but the argparse pin (already live, currently vacuous) makes correctness here binary, not gradual — closer in shape to the round-7-pins commit (418 insertions) than to slice 0's feature commit | ~45–60k |
| **a3 — the guard** | arming, the verb-effect table, guard integration at ~11 existing call sites, the two §7 pins from Ambiguity #1 | Depends on a2's resolved-home value existing at every call site. The most dispersed-edit-heavy piece (§3's argument), and the one most exposed to Risk 2 below | ~80–110k |

Total ≈ 195–260k against a single lane's 150–200k band — **confirmed too big for one slice as
Sequencing §3 currently states it**, before accounting for any fix-wave/review overhead this
repo's own history shows every prior slice absorbing (slice 0 shipped clean on its first commit
pair; most earlier gate-track slices did not). **Do not consume the spec's own reserved letters
`b`/`c`/`d`/`e` for this split** — those already name later, different slices (`init --home`;
hook argv; statusline; pins). Name the pieces `a1`/`a2`/`a3` (or similar sub-numbering) so the
Sequencing table's own vocabulary stays unambiguous if this split is adopted.

If the operator prefers one lane regardless: expect a lane that either runs two-plus turns before
its first commit, or ships a1 clean and needs a fix wave for a2/a3's guard-integration misses —
this repo's own named recurring defect (see the round-7 pins file's own B2 section: "fixing only
the reported site is how this project reproduces a miss at the next site").

## 6. Risks, ranked, each with what resolves it

1. **`read_registry_at` may inherit a measured, currently-shipped defect whose blast radius
   multi-fleet explicitly multiplies.** `_read_registry_readonly` (`bin/fleet.py:3834`, the
   existing sibling this new function generalizes) catches
   `(json.JSONDecodeError, UnicodeDecodeError, OSError)` and nothing else — confirmed still
   true today (`bin/fleet.py:3873`, unchanged since round 6). `REPORT-mf-rs6.md` (C-4,
   round-6 spec lens) measured a deeply nested JSON document raising an uncaught
   `RecursionError` through this exact except-clause shape, with an oversize document reaching
   `MemoryError` by the same route. That was a **bounded** pre-existing defect when only your
   own home was ever read. Multi-fleet's own §5.2 changes the exposure: **one lock-free
   `read_registry_at` snapshot per listed home, on every sid-carrying invocation** — so one
   corrupt (or adversarial) registry in *any* listed home now takes down every verb and every
   view on the machine, including the statusline, whose standing rule (root `CLAUDE.md`)
   requires it to always exit 0. **Resolves:** the 12-shape RED-first fixture set for
   `read_registry_at` must include a recursion-bomb and an oversize-document shape explicitly
   (the round-3 sweep evidently didn't), and the function must catch `RecursionError` and
   `MemoryError` alongside the existing three, not merely copy the sibling's except-clause.
2. **Guard integration at ~11 scattered call sites is exactly this project's own named
   recurring defect shape.** The round-7 pins file's own docstring (B2 section) documents this
   happening *twice already* in this same codebase: a fix aimed at one reported site (the
   `DESTRUCTIVE_VERBS` enumeration) missed three siblings until a derived, re-run comparison
   caught them. Slice a3's guard touches a comparable count of call sites for the first time.
   **Resolves:** derive the call-site list by grep/AST against `build_parser()`'s own choices at
   build time (as slice 0 did for the `FLEET_HOME / "bin"` lint), not by copying this document's
   or the spec's prose list — a re-derived census is what caught the miss last time.
3. **Cross-home read cost at scale is unmeasured.** §5.2 requires one registry read per listed
   home per sid-carrying invocation — O(N-homes) where today's single-fleet resolution is O(1).
   No number for N (how many homes accumulate on a real machine over time) exists anywhere in
   this repo. **Resolves:** once a1 lands (the homes list exists), benchmark against this
   machine's own real list size before a3 makes every verb pay the cost per-invocation.
4. **A bare-word naming collision risk, not yet realized.** Multi-fleet's "armed" (population
   ≥2 homes) and claim-nonce's already-shipped "armed" supervisor-claim-gate concept
   (`tests/test_gate_arm_wedge.py`, `test_supervisor_gate.py`) share a word inside the same
   19.7k-line module. No actual code overlap exists today (verified: the existing "armed" hits
   are all in the unrelated supervisor-gate test files). **Resolves:** prefix multi-fleet's
   arming symbols distinctly (e.g. `_homes_population_armed`, not a bare `armed`/`_is_armed`)
   so a future grep or a tired reader doesn't conflate the two.
5. **The argparse pin currently proves nothing about a *real* reconciliation choice.** Its seed
   test proves the detector isn't dead code, but the detector itself only checks "does any
   subparser redefine a top-level dest" — a builder could satisfy that by renaming `autoclean`'s
   local dest to something else entirely (`fleet_home_autoclean`) while leaving the *global*
   value silently unreachable from inside `autoclean`'s own subcommand, which would pass the
   lint while still being wrong (silently dropping the flag from a different angle). **Resolves:**
   whoever builds a2 re-reads the file's own prescription before choosing a mechanism — "share
   one parser object" is the safer of the two remedies the spec names, because "reconcile
   explicitly" has more ways to be wrong that this lint doesn't check for.

## Bottom line

The document is buildable today (§1). Slice (a) is well-scoped by the spec (§2) but is the
single largest and most heterogeneous slice in the whole build order — three new subsystems
plus a guard dispersed across roughly a third of the CLI's verbs, in a 19,693-line single file,
starting from zero test coverage for all of it. **Recommend splitting into a1 (data layer) → a2
(resolution + flag) → a3 (guard), landed by separate lanes or separate turns, each RED→GREEN on
both interpreters before the next starts** — the combined estimate (~195–260k) does not fit one
lane's 150–200k band, and the guard piece (a3) is where this project's own named recurring
defect (fix-one-site, miss-the-rest) is most likely to recur. Before dispatching a1, resolve
Ambiguity #3 (locate or re-derive the twelve corruption shapes) and confirm Ambiguity #1's
reading of §7 with the operator if it materially changes the estimate.
