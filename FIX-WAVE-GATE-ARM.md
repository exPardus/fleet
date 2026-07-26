# FIX WAVE — `fix/gate-arm-released`, 2026-07-27

Worker `gate-arm`, worktree `C:/proga/fleet-gate-arm`. Input: `state/tasks/briefs/ga-fix-wave.md`
(supervisor's ruling), against `C:/proga/fleet-ga-rb/REVIEW-BREAK-GATE-ARM.md` (break lens) and
`C:/proga/fleet-ga-rs/REVIEW-SPEC-GATE-ARM.md` (spec lens). Both read in full before any edit.

**New file, not an edit of `REVIEW-INPUT-GATE-ARM.md`** — that document is the record of what the
two lenses reviewed, and rewriting it in place would destroy the thing their findings are anchored
to. This is the delta.

One commit: `a6d195a`, on `fix/gate-arm-released` only. Nothing pushed.

| | |
|---|---|
| Scope | 8 blocking items, all executed. **One executed differently than ordered — item 4, with evidence, below.** |
| Both floors | **2221 passed / 11 skipped** on `py -3.13` AND `py -3.10` (baseline 2185/11; **+36 new, 0 pre-existing tests changed outcome**) |
| Receipts | `58/59, 0 failures, 1 warning` — the inherited `:1357` mtime, unchanged |
| Mutation | **12 of 13 killed; the 13th proved EQUIVALENT**, not a gap |
| Sessions created | **zero** — `claude agents --json --all` shows the same 22 pytest entries rb reported, 0 live |
| Fences | all held (§10) |

---

## 0. What the delta count means

`2221 = 2185 + 36`, and the 36 decompose exactly:

| File | New | What |
|---|---|---|
| `tests/test_supervisor_gate.py` | +13 | `sup-spawn` added to `GATED_VERBS` (+1 on the held arm), the taxonomy-coverage test (+1), the wedged arm parametrised over all 11 (+11) |
| `tests/test_gate_arm_wedge.py` | +9 | union-arm message (2), never-crash (5), archive gate 3b (1), the T9 C1 boundary (1) |
| `tests/test_b6_sid_union.py` | +10 | the fork-steer/respawn boundary (6) and its degradation matrix (4) |
| `tests/test_retired_sid_citations.py` | +4 | the citation harness |

No pre-existing test was deleted, skipped, or flipped. Three existing tests had their **fixtures**
rewritten (they now stamp `created` explicitly rather than inheriting `now_iso()`); all three still
assert the same thing and still pass. One existing test, `test_rm_skips_a_live_retired_sid_but_rms_
current_sid`, went RED mid-wave and is the subject of item 4.

---

## 1. CRIT-1 — the wedged arm over the §7 verb taxonomy

**Changed.** `GATED_VERBS` is now shared by both arming arms through one `_gated_argv(verb, home)`
helper, and `TestEveryMutatingVerbIsGatedByTheWedge` drives every verb in it through a wedged claim.

**The list also gained `sup-spawn`** — this is a widening of the item, declared. §7's taxonomy plus
the later amendment is **eleven** verbs; `GATED_VERBS` carried ten, so a carve-out disarming
`sup-spawn` alone was invisible to the **held** arm too, which is the pre-existing version of exactly
the defect CRIT-1 names. A new test reads the taxonomy back out of the source
(`test_the_taxonomy_covers_every_call_site_in_fleet`) and fails if any `_supervisor_gate("verb")`
call site is missing from the list, so the list cannot silently fall behind the code again.

**Pinned by.** `tests/test_supervisor_gate.py::TestEveryMutatingVerbIsGatedByTheWedge`
(11 parametrised cases) and `::TestEveryMutatingVerbIsGated::test_the_taxonomy_covers_every_call_
site_in_fleet`.

**RED→GREEN.** RED here is *not* "the old code fails" — the old code armed correctly for all eleven
verbs; what was missing was the ability to notice if it stopped. The evidence is therefore the
mutation table, re-run in rb's driver shape, on the **full suite**:

```
# scratch driver, $CLAUDE_JOB_DIR/tmp/mutate.py, --full
X1-carveout-7-verbs      killed rc=1 | ['9 failed, 2212 passed, 11 skipped']
      FAILED ...TestEveryMutatingVerbIsGatedByTheWedge::test_verb_is_refused_under_a_wedged_claim[sup-spawn]
      FAILED ...[send] [respawn] [archive] [resume-limited] [release]
X2-carveout-send-only    killed rc=1 | ['3 failed, 2218 passed, 11 skipped']
      FAILED ...TestEveryMutatingVerbIsGatedByTheWedge::test_verb_is_refused_under_a_wedged_claim[send]
```

Both of rb's survivors die. `X0-seed-disarm-the-wedge` (34 failures) is the driver's own seed.

---

## 2. MAJ-1 — the refusal prints the sid that is actually live

**Changed.** `_releaser_live_sids(claim, live_sids, registry)` is the comparison and returns the set
of roster-live sids attributable to the releasing body; `_releaser_is_roster_live` is now its boolean
spelling — kept under that name because §6.1 row 1 and §7.2 both cite it and §6.1 is ratified text I
may not edit. Both consumers decide through the boolean and reach for the set only to name sessions,
so the decision and the message cannot drift.

The gate's refusal now prints **both**: `released_by` as identity, and the live sids as the remedy
("*escalate to the operator, who can stop session(s) `<live>` directly — those are the live ones;
sid `<released_by>` may already be gone*"). B6's boot refusal got the same treatment.

**Pinned by.** `test_the_union_arm_names_the_session_that_is_actually_live` (the fixture rb built)
and `test_the_refusal_never_names_a_roster_gone_session_as_the_remedy` — the general form, which
parses the remedy clause out of the message and asserts the sids it offers are exactly the roster-live
set, so this cannot regress for a shape nobody wrote a fixture for. The existing bare-arm pin was
extended with the same `stop session(s) …` assertion rather than replaced.

**RED→GREEN.** Against `bin/fleet.py` @ `badd568`, tests unchanged:

```
FAILED tests/test_gate_arm_wedge.py::...::test_the_wedge_refusal_names_only_exits_that_execute
FAILED tests/test_gate_arm_wedge.py::...::test_the_union_arm_names_the_session_that_is_actually_live
FAILED tests/test_gate_arm_wedge.py::...::test_the_refusal_never_names_a_roster_gone_session_as_the_remedy
E   assert 'stop session(s) sid-post-fork' in 'clean: refusing -- ... its releasing body
    (sid sid-pre-fork) is still live in the roster ...'
```

Mutants `X5-refusal-names-released-by-only` and `X6-live-sids-not-intersected` both killed.

---

## 3. MAJ-2 — the union arm bounded to the un-restamped fork-steer window

**The boundary drawn, and it is drawable.** The record's own `created` against the claim's
`released_at`: **a record minted after the release cannot be the body that performed it.**

| Path | What it does to the record | Verdict |
|---|---|---|
| fork-steer (`_restamp_after_steer`) | mutates IN PLACE — `session_id` := the fork, old sid appended to `retired_sids`; `created` untouched | `created ≤ released_at` → **ARMS** (ND4a) |
| respawn (`cmd_respawn`) | REPLACES the record with `new_worker_record(...)`, fresh `created` stamped at respawn time | `created > released_at` → **declines** |
| `_cmd_respawn_supervisor` | mints a differently-**named** record, leaves the old one behind | never carries the releaser's sid — no case needed |

**Why the anchor is sound, checked rather than assumed.** `created` is written at exactly one site in
the whole file — `new_worker_record` — and is never rewritten in place:

```
$ grep -n '"created"' bin/fleet.py
998:        "created": created,          <- the only writer
2381,2464,4247: rec.get("created")       <- reads (fresh-outcome anchors)
10256:          _parse_iso(rec.get("created"))   <- this predicate
```

So "the record already existed when the claim was released" is a fact the registry actually records,
not an inference.

**Degradation, one direction, stated once and pinned four ways.** No parseable `released_at`, no
parseable `created`, or a registry fleet cannot read → that record drops out of the union and the
bare `released_by_sid in live_sids` comparison is all that remains, which is `main`'s shipped answer.
The direction is deliberate: it resolves toward the failure an operator can still act on (a fail-open
B6, refusable at the next boot) rather than the one that needs a human with a text editor. The tie
(`created == released_at`, both second-precision) resolves the other way, **toward the gate**.

**Pinned by.** `tests/test_b6_sid_union.py::TestTheUnionArmIsBoundedToTheForkSteerWindow` — both of
rb's fixtures, each driven to the **last verb**:

- fork-steer arms: `clean --yes` → rc 4 and the tombstone survives; `sup-boot` → `refuse` and the
  claim is still `released`.
- respawn does not: `clean --yes` → rc 0 and the tombstone is deleted; `sup-boot` → `claim`, a new
  incarnation id, `session_id == sid-successor`. **That last assertion is MAJ-2's harm reversed** —
  the in-fleet exit exists again.
- the tie arms; the four degradation shapes each disarm while the bare arm still arms.

**RED→GREEN.** Against `badd568`:

```
FAILED ...::test_a_respawned_body_does_not_arm_the_gate
E   AssertionError: a respawn chain kept the fleet wedged
FAILED ...::test_a_respawned_body_leaves_an_in_fleet_exit
E   AssertionError: no successor could ever boot
FAILED ...::test_an_undrawable_boundary_degrades_to_the_bare_comparison  [x4]
6 failed, 16 passed
```

Mutants `X3-drop-the-fork-steer-boundary` and `X4-undrawable-boundary-arms` (degrading the other way)
both killed.

---

## 4. MAJ-3 — **executed differently than ordered.** Push-back, with the measurement

**The order was:** re-key `_archive_eligible` gate 3 through `_record_sids`, as the eighth ND4a site.

**I wrote that first. It reverses a prior ruling, and the suite caught it:**

```
FAILED tests/test_native.py::TestCmdArchive::test_rm_skips_a_live_retired_sid_but_rms_current_sid
E   assert set() == {'aaaabbbb'}
    archived 0 worker(s), skipped 1
```

That test carries T9 fix-wave finding C1 (CRITICAL) in its own comment: a fork-steer leaves the
parent's roster entry untouched, so an ordinary worker can carry a **live retired sid** indefinitely;
the rm loop must skip that sid *"and still archive everything else"*, because a live retired sid is
explicitly *"not a reason to block the whole worker"*. Re-keying gate 3 onto the union makes every
such worker permanently un-archivable, fleet-wide. The ruling's *"this is the eighth"* framing is
right about the identity concept and wrong about this site: the other seven re-keys ask *"is this
body live?"*; gate 3 asks *"is it safe to move this record's files and rm its session?"*, and T9
already decided those are different questions.

**What shipped instead: gate 3b.** MAJ-3's measured harm is narrower than the re-key — it is that
*the record the §7 gate is currently wedging the fleet on* is archive-eligible, so `autoclean` can
delete the state the gate reads (rb's second half, the ARMED→DISARMED flip). Gate 3b refuses exactly
that record, decided through the **same predicate the gate arms on** (`_releaser_live_sids` over a
one-record registry), so the archive gate and the §7 gate cannot come to disagree about what a wedge
is. It releases the moment the wedge does. Gate 3 is untouched.

**Pinned by.** `test_the_record_wedging_the_fleet_through_the_UNION_is_protected_too` — which asserts
**both halves on one record** (it arms the gate AND is ineligible), because the claim being made is
that they are the same state — and `test_an_ordinary_worker_with_a_live_retired_sid_is_still_
archivable`, which is T9 C1's contract restated at the boundary of the new gate.

**RED→GREEN.** Against `badd568`, with an outcome record written so gate 3b is the only thing left
standing (without it the record stops at gate 4 and the defect hides behind `no-outcome-record` — I
hit that and strengthened the fixture):

```
FAILED ...::test_the_record_wedging_the_fleet_through_the_UNION_is_protected_too
E   AssertionError: the record wedging the fleet is archivable
E   assert True is False
```

Mutants: `X7-drop-archive-gate-3b` killed; **`X8-rekey-gate-3-onto-the-union` killed, and by the T9
test** — the pushback is executable, not an opinion:

```
X8-rekey-gate-3-onto-the-union  killed rc=1 | ['5 failed, 646 passed, 1 skipped']
      FAILED tests/test_gate_arm_wedge.py::...::test_an_ordinary_worker_with_a_live_retired_sid_is_still_archivable
      FAILED tests/test_native.py::TestCmdArchive::test_rm_skips_a_live_retired_sid_but_rms_current_sid
```

**If the supervisor still wants the full re-key**, it is a deliberate reversal of T9 C1 and needs
that test changed with a reason attached — not a side effect of this wave.

---

## 5. MAJ-4 — `dispatch_bg` stubbed for the CLASS, not the two tests

**Changed.** An autouse `_never_dispatch` fixture in **all three** gate test files
(`test_supervisor_gate.py`, `test_gate_arm_wedge.py`, `test_b6_sid_union.py`) replaces `dispatch_bg`
with `pytest.fail`. The per-test stub that this branch added to one test is removed in favour of it,
so there is exactly one mechanism. A test that legitimately needs a dispatcher stubs its own after
the fixture.

Scoped to these files rather than to `tests/conftest.py` deliberately: 37 test files reference
`dispatch_bg`, and `tests/test_native.py` calls it **directly** with a fake `run=` to test dispatch
itself. A global autouse stub would break those legitimately.

**This was done FIRST**, before any other item, and before driving a single verb — trap 3 of the
brief.

**Evidence it holds.** `claude agents --json --all` after the whole wave (many full-suite runs, two
floors, 14 mutation runs):

```
total entries: 88
pytest-dir entries: 22 | LIVE: 0
[('2256',2),('2262',2),('2264',2),('2266',2),('2272',2),('2279',2),('2283',2),
 ('2290',2),('2309',2),('3138',1),('3141',1),('3152',1),('3154',1)]
```

The same 22 rb reported (their 18 + this branch's 4), zero new, zero live. My pytest dirs contributed
none.

---

## 6. MIN-1 — the wedged arm inside the never-crash guard

**Changed.** `_supervisor_gate` now calls `_wedged_release_gate` inside a `try`, with
`except SupervisorClaimGateError: raise` **before** the blanket `except Exception: return`. The
re-raise is the load-bearing half: a bare guard would disarm the gate on its own armed path.

**Pinned by.** `TestTheWedgedArmCannotCrashAVerb` — 5 tests: a `RuntimeError` from the roster and an
`OSError` from the registry read, each driven to the **last verb** (`clean --yes` completes and
deletes, exactly as the gate's other fail-open arms do) and each driven at the gate frame rb used;
plus `test_the_never_crash_guard_does_not_swallow_the_refusal`.

**RED→GREEN.** Against `badd568`: 4 failures with the raise escaping `_supervisor_gate`. Mutants
`X9-arm-outside-the-never-crash-guard` (killed) and `X10-never-crash-guard-swallows-the-refusal`
(killed, 34 failures — it disarms the whole slice).

---

## 7. S-7 — the four citations re-pinned, and made un-rottable

**Changed.** `:4505, :4952, :8061, :11147` → the real writers, in both docstrings that carry them.
The numbers are now `:4566, :5013, :8941, :12411` **at this commit**.

**And a harness, because re-pinning without one just resets the clock.**
`tests/test_retired_sid_citations.py` re-derives the numbers from the source on every run and asserts
three things:

1. every cited line really is a `retired_sids` write;
2. **every `retired_sids` write is cited** — so a NEW writer, the one that could actually break the
   invariant, cannot be added silently;
3. every writer appends only its own record's prior sid — the invariant itself, not its citation.

It has its own seed check (`test_the_citation_block_is_found_at_all`), because a regex that silently
matches nothing would make every other assertion pass vacuously — the same reason
`verify_receipts.py` self-tests.

**RED→GREEN.** Against `badd568`:

```
E   AssertionError: bin/fleet.py:4505 is cited as a `retired_sids` writer and is not one:
    'session. Called with the pre-claim (status="working") already'
E   AssertionError: uncited `retired_sids` writers: [4566, 5013, 8900, 12248];
    citations pointing at no writer: [4505, 4952, 8061, 11147]
```

Mutant `X11-citation-drifts-by-one-line` (inserting a single blank line above a writer) killed. It
also caught **my own** drift twice during this wave, which is the point.

**Declared cost.** Any future edit to `bin/fleet.py` that inserts or removes lines above `:12411`
will fail these two tests until the citations are re-pinned. That is the same bargain the repo
already takes for `# at <sha>` receipt pins, and the failure message prints the correct numbers, so
the fix is one line. If the operator judges the friction too high, the honest alternative is to
delete the line numbers from both docstrings and cite by function name — **not** to keep numbers
nobody checks.

---

## 8. S-2 — §7.2 narrowed to what is true

**Changed** (`docs/specs/claim-nonce.md` §7.2, this branch's own PROVISIONAL text — the only spec
text edited, plus nothing else):

- *"neither can be shown to lose anything in the wedged state"* is **withdrawn as false**, in those
  words. What replaces it is the narrower true statement: the ordering guarantee holds *while the
  gate is armed*, and on the fail-open arms `:2005`'s released early-out leaves the ceiling dormant
  exactly as on `main` — spelled out with the concrete path (roster unreadable → gate returns →
  `_caller_holds_supervisor_claim` sees `released` → `False` → ceiling dormant → a body above
  `BAND_HARD_TOKENS` dispatches with neither guard firing).
- A new **"Open items this subsection does NOT close"** table files three things instead of closing
  them by assertion: the `:2005`/`:2059` early-out, the §7.1 `send` carve-out's `load_registry()`
  quarantine (rs S-5 — filed, not fixed, as ordered), and §7's unratified arming envelope (rs S-1 —
  **the operator's**, named as theirs).
- §7.2's shipped-rule section now also describes the fork-steer boundary (a second table), the
  degradation direction, and the MAJ-1 message rule — because §7.2 documenting a predicate that no
  longer ships would be a fresh instance of this repo's named recurring defect. Declared as a
  widening of item 8.

**No ratified section was amended. Nothing was marked ratified. §7's body, §6.1, §6.3 and rs's
S-1/S-3/S-4/S-6 are untouched.**

**Verified.** `py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/claim-nonce.md`
→ `58/59 reproduce exactly, 0 failures, 1 warning` (the inherited `:1357` mtime).

---

## 9. Mutation ledger — 13 mutants, chosen as a later maintainer would write them

Driver `$CLAUDE_JOB_DIR/tmp/mutate.py`; each mutant applied to `bin/fleet.py`, suite run, file
restored and sha-verified in a `finally`.

| # | Mutant | Verdict | Killed by |
|---|---|---|---|
| X0 | seed — disarm the wedged arm entirely | killed (34 fail) | the whole wedge file |
| X1 | carve-out disarming 7 of 11 verbs | killed (full suite) | wedged taxonomy `[sup-spawn]`, `[send]`, `[respawn]`, `[archive]`, `[resume-limited]`, `[release]` |
| X2 | carve-out disarming `send` only | killed (full suite) | wedged taxonomy `[send]` |
| X3 | drop the fork-steer boundary | killed | `test_a_respawned_body_does_not_arm_the_gate` |
| X4 | undrawable boundary ARMS instead of dropping out | killed | the degradation matrix |
| X5 | refusal names `released_by` as the remedy again | killed | `test_the_union_arm_names_the_session_that_is_actually_live` |
| X6 | predicate stops intersecting with the roster | killed | `test_the_refusal_never_names_a_roster_gone_session_as_the_remedy` |
| X7 | drop archive gate 3b | killed | `..._wedging_the_fleet_through_the_UNION_is_protected_too` |
| X8 | **the ordered fix** — re-key gate 3 onto the union | killed | T9 C1's `test_rm_skips_a_live_retired_sid...` (§4) |
| X9 | arm outside the never-crash guard | killed | `TestTheWedgedArmCannotCrashAVerb` |
| X10 | never-crash guard swallows the refusal too | killed (34 fail) | the whole wedge file |
| X11 | a cited writer drifts one line | killed | the citation harness |
| X12 | drop the `registry is not a dict` early return | **EQUIVALENT** | — see below |

**X12 is equivalent, not a survivor.** rb's MIN-3 asked whether a guard that looks redundant is one.
Re-checked on the new code, executed rather than argued:

```
$ py -3.13 -c "... _releaser_live_sids(claim, {'s2'}, registry=REG)"
None -> set()      'not-a-dict' -> set()   123 -> set()
[]   -> set()      {} -> set()             {'workers': {}} -> set()
with a matching record -> {'s2'}
```

The mutant substitutes `registry = {}` for the early return, and `{}` yields `set()` by the same
path. No input distinguishes them. Left as-is per the brief's "leave it or simplify it; do not build
a mechanism around it" — the guard documents the degradation contract even where it is not
load-bearing.

---

## 10. Fences

| Fence | Status |
|---|---|
| No `git push` of any ref | **held** — no network git command run |
| No merge / rebase / cherry-pick | **held** |
| `main`, other worktrees, other branches untouched | **held** — the two review worktrees were read only |
| No `fleet` mutating verb, no `sup-*` verb against the real fleet | **held** — every verb driven inside a pytest `tmp_path` `FLEET_HOME` |
| Live daemon / `~/.claude/daemon.lock` untouched; no `claude daemon stop` | **held** — the only `claude` invocation was the read-only `claude agents --json --all` audit in §5 |
| No session created | **held** — 22 pytest entries, all pre-existing, 0 live (§5) |
| Commits to `fix/gate-arm-released` only | **held** — one commit, `a6d195a` |
| Scratch in `$CLAUDE_JOB_DIR/tmp`, never `state/tasks/gate-arm.md` | **held** — `mutate.py`, `repin_citations.py`, `fleet.py.mine` |

`bin/fleet.py` was mutated 14 times and restored + sha-verified after every run:

```
restored: 22b520b67eef1b66468e823ecf70b865b25f49722eaeae52fece8cdb58bf000b
```

---

## 11. Push back on this

Ordered by how much I think it matters.

1. **Item 4 is the one I did not execute as written, and the evidence is in §4.** The re-key
   reverses T9 finding C1 for every ordinary fork-steered worker. I shipped the narrower gate 3b.
   If you want the re-key anyway, it is a reversal that owes T9 C1 a written reason, and it should
   be its own change with `test_rm_skips_a_live_retired_sid_but_rms_current_sid` amended
   deliberately.

2. **The item-3 boundary rests on a fact, but it is a fact about `cmd_respawn` specifically.** The
   invariant I am relying on is "no code path rewrites an existing record's `created`", and I
   verified it (`created` has exactly one writer, §3). If a future path ever carries `created`
   forward across a respawn — which would be a *reasonable* thing to want, to keep a worker's age
   readable across respawns — the boundary silently inverts and MAJ-2 comes back. That deserves a
   one-line comment at `new_worker_record`, which I did **not** add because I was not sure it is in
   scope. Say the word.

3. **The union arm's `created` boundary makes the gate's verdict depend on the registry more, not
   less** — and rb's second half of MAJ-3 (the union arm depends on a record that ungated paths can
   delete) is *narrowed* by item 4's gate 3b but not eliminated: `_expire_tombstones` and
   `_sweep_husks` still delete records without passing the gate. The wedge disarming because
   something deleted the record is still reachable. I did not fix it — it is out of this brief's
   eight items and the fix is a design question (should the gate fail toward armed when the record
   it expected is gone?). Filed here rather than in the spec because it is not a §7.2 claim.

4. **`GATED_VERBS` gaining `sup-spawn` is a widening I made unilaterally.** It closes a hole in the
   *held* arm that predates this branch. If you would rather the held arm's coverage not change in a
   fix wave, revert that one list entry — the wedged arm still covers ten.

5. **The citation harness has a running cost** (§7): every future line-shifting edit to
   `bin/fleet.py` needs a re-pin. I think it is the correct trade for this repo's named recurring
   defect, but it is a standing tax on an actively-edited file and you may disagree. The scratch
   tool that does the re-pinning is `$CLAUDE_JOB_DIR/tmp/repin_citations.py` — **it is outside the
   repo and will vanish with this job**. If you want the harness kept, that tool should probably
   move into `tools/`, which I did not do unasked.

6. **rs S-1 is still open and it is the largest thing in either review.** The gate is armed with no
   heartbeat and no time bound, which contradicts §7's ratified *"armed only while the heartbeat is
   fresh"*. You said you are writing that `OPERATOR-GATES.md` entry. Nothing in this wave changes
   the arming envelope; item 3 only makes it strictly narrower.

7. **One thing I could not do and want to flag rather than paper over:** none of this has been driven
   against a real wedge. Every wedge in the suite is a `tmp_path` `FLEET_HOME` with a stubbed roster,
   because the fences (correctly) forbid `sup-*` verbs against the live fleet. The first real
   `sup-release` after this merges is the first execution of the union arm's boundary against a real
   `created` timestamp. That is a good reason for the operator to schedule that release rather than
   let it happen incidentally.
