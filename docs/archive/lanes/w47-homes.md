# Lane report — `w47-homes`

**Lane.** The homes/E2 split: reading `fleet homes` stays ORDINARY, `--add`/`--retire` become
DESTRUCTIVE (operator ruling 2026-08-08, `docs/OPERATOR-GATES.md` `## Settled`), plus the
`w47-ga3` gate's **A-1** — make *"the worst matching tier wins"* exercisable.

**Branch.** `w47/homes`, branch point **`e5889fe`** (MEASURED: `git rev-parse main`, `HEAD` and
`git merge-base HEAD main` were all `e5889fe` at dispatch, tree clean).

**Verdict.** Both halves landed. The ruling's *behaviour* is exactly what the brief predicted; the
ruling's *shape* is not — see WHERE THIS BRIEF WAS WRONG, which is the section worth reading first.

---

## 1. The brief's three measured claims, re-derived

Re-derived against the shipped resolver at `e5889fe` by driving the **real** `build_parser()`, not
a hand-built namespace (`--add`/`--retire` dests are the entire mechanism, so an invented namespace
could agree with the table while the CLI did not).

| # | Claim | Verdict |
|---|---|---|
| 1 | `homes` is a bare token in `VERB_EFFECT_ORDINARY` → `dest=None` → `fleet homes --add` classifies `ordinary` today | **MEASURED TRUE** |
| 2 | `--add`/`--retire` take argparse's default dests (`add`, `retire`), no `dest=` override, so no `VERB_EFFECT_RESIDUAL_FLAGS` entry is needed | **MEASURED TRUE** |
| 3 | Appending `"homes --add"`/`"homes --retire"` to `VERB_EFFECT_DESTRUCTIVE` yields bare→ordinary, `--add`→destructive, `--retire`→destructive | **MEASURED TRUE of the resolver, and NOT SUFFICIENT as a landing** — §5 |

MEASURED, claim 1 — `_verb_effect_index()["homes"]` was `((None, 'ordinary'),)`, and through the
real parser `fleet homes` → `ordinary`, `fleet homes --add C:/x` → `ordinary`, `fleet homes
--retire C:/x` → `ordinary`. The last two are what the ruling forbids.

MEASURED, claim 2 — both options are `_StoreAction`, `default=None`, `dest='add'` / `dest='retire'`;
the mechanical `--x-y` → `x_y` rule yields `add` / `retire`; `'homes' not in
VERB_EFFECT_RESIDUAL_FLAGS`. Pinned going forward by
`test_no_homes_entry_is_needed_in_the_residual_flags_escape_hatch`.

MEASURED, claim 3 — with the two tokens appended in memory: bare → `ordinary`, `--add` →
`destructive`, `--retire` → `destructive`. Under that shape `matched == ['ordinary',
'destructive']`, `max` → `destructive` and `min` → `ordinary`, so `max` would indeed have become
load-bearing. That shape was **not landed**; §5 explains why.

## 2. Both directions of the check the brief demanded

The brief required checking the shipped table against the ruling in BOTH directions and REPORTING
(not fixing) any other verb whose shipped tier contradicts a ratified row.

- **No contradiction found in the shipped table.** MEASURED structurally rather than by eye: the
  three production tuples are pinned equal to the three `RATIFIED_*` tuples
  (`test_production_and_the_pin_file_transcribe_the_same_table`), which are themselves pinned
  against §5's rows in both directions. A shipped-vs-ratified contradiction is already RED by
  construction, and the floor was green at `e5889fe`.
- **`homes` is NOT in `TERMINUS_VIEW_VERBS`** (MEASURED). There is no second surface repeating the
  `doctor --repair` split here; `homes` sits in the machine-level tuple, whose own comment records
  that putting it in the view tuple once made `fleet homes --add` print `[fleet]: no home` and
  exit 0 without appending.
- **The grant hole this ruling closes is PROSPECTIVE, not live** (MEASURED). No `commands/homes.md`
  ships, so no read-only slash command grants `Bash(fleet homes)` today. The lint entries are what
  keep it shut when one lands.
- **REPORTED, not fixed — one adjacent row.** `init` is ratified **ordinary**, and §4's homes-list
  commentary names *"`init --home`, slice b"* as a second writer of the same machine-global list.
  If slice b ships an appending `init --home` while `init` is bare-ordinary, the E2 ground reaches
  it exactly as it reached `--add`. MEASURED: slice b is unbuilt at `e5889fe` — `init` declares
  `--nonce`, `--statusline`, `--chain`, `--force` and no `--home` — so there is no shipped
  contradiction to repair. Reclassifying a ratified row is an operator edit. Recorded in §5 as
  that note's *one residual* and raised here for the operator.

## 3. Why the brief's two tokens were not a landing — the finding

**MEASURED.** The brief's shape leaves bare `homes` in `VERB_EFFECT_ORDINARY` and adds the two
flagged tokens to `VERB_EFFECT_DESTRUCTIVE`. That puts one verb in **two rows**, and two shipped
pins forbid exactly that:

- `tests/test_verb_effect_guard.py::test_no_verb_is_in_two_rows` — production tuples. Probed:
  `destructive & ordinary` first-tokens = `['homes']`, assertion **False**.
- `tests/test_round7_defect_pins.py::test_no_verb_IS_NAMED_BY_TWO_spec_rows` — §5's rows. Probed
  against a spec carrying the brief's shape: `{'homes': ['destructive', 'destructive',
  'ordinary']}`, assertion **False**. Its own message is the reason: *"an effect class is a
  partition — a verb in two rows means whichever row a reader finds first decides how it is
  guarded."*

**The shipped idiom for this exact shape already exists and is `doctor`.** MEASURED: bare `doctor`
is in **no** tuple, `doctor --repair` is in the destructive tuple, and
`VERB_EFFECT_RESIDUAL['doctor'] == 'ordinary'`. The residual block's own comment says it is *"what
a verb the table names ONLY with a flag qualifier is when that flag is absent"* — which is a
verbatim description of what the operator ruled for `homes`. So `homes` became the third verb in
that shape rather than the first verb in two rows.

**It is also the safer of the two, and this is the part I would defend hardest.** BELIEVED, with
the mechanism MEASURED: under the brief's two-row shape, dropping the flagged tokens sends the
writes back to **ORDINARY** — fail-open, and precisely the hole the operator just closed. Under
the residual shape the same slip leaves `homes` in no tuple at all, and an unclassified verb is
**destructive** — fail-safe. The runtime answers are identical; the degradation modes are
opposite.

## 4. The diffs

`449 insertions, 60 deletions` across the five fenced files, and nothing outside the fence
(MEASURED: `git status --porcelain` lists exactly those five).

### `bin/fleet.py` (+74 / −32)

The classification change is three lines of data:

```
-                           "sup-spawn", "sup-checkpoint", "sup-release")
+                           "sup-spawn", "sup-checkpoint", "sup-release",
+                           "homes --add", "homes --retire")
-VERB_EFFECT_ORDINARY = ("spawn", "init", "status", "peek", "result", "homes",
+VERB_EFFECT_ORDINARY = ("spawn", "init", "status", "peek", "result",
-VERB_EFFECT_RESIDUAL = {"doctor": "ordinary", "sup-decision": "ordinary"}
+VERB_EFFECT_RESIDUAL = {"doctor": "ordinary", "sup-decision": "ordinary",
+                        "homes": "ordinary"}
```

*(Illustrative excerpt of a tracked diff, not a receipt — this document is not under
`docs/specs/**` and carries no `# at <sha>`.)*

The rest is prose that had gone stale on contact: the residual block said *"Two verbs are in that
shape"* (now three, with the ruling and both grounds cited); `_verb_effect_index`'s docstring said
*"both ratified flag-qualified tokens"* (now four, measured off `build_parser()`); and
`verb_effect_tier`'s `max` paragraph claimed the rule was doing work — see §5.

**Plus 31 self-citation re-pins, +1 range end.** The brief budgeted for this and it arrived: the
+42-line insertion shifted every citation below it. MEASURED via `difflib.SequenceMatcher` over the
branch-point and working line lists, with **per-citation content verification** — each rewrite was
accepted only when the new line was byte-identical to the line the old number named — and never by
adding a constant. 0 unresolved. One ranged citation (`` `cmd_respawn:8434-8394` ``) needed a
second pass: the range END carries no colon, so the `:(\d+)` scanner never saw it, and the file was
RED on 2 range tests until it was mapped (8394 → 8436, content-verified) the same way.

**One self-inflicted hazard, caught and repaired before the floors.** The first apply wrote the
file with `newline=""` from text read under universal newlines, converting all **21402 CRLF line
endings to LF** — a whole-file diff masquerading as a 31-number edit. Caught by checking the byte
counts immediately after the write, repaired, and the diff verified back down to 106 changed lines.
Every subsequent write to `bin/fleet.py` asserts `CRLF == 21402 and bare LF == 0`.

### `docs/specs/multi-fleet.md` (+70 / −6)

Appended in E5's idiom (`8f11b0e`, `63d7bf6`), never rewriting ratified text:

- **Destructive row** gains `` `homes --add` `` and `` `homes --retire` `` with the E2 ground.
- **Ordinary row**: the superseded entry is annotated **in place** rather than deleted — and the
  verb name inside that annotation is deliberately **unbackticked**. Both traps the brief named
  were live: the row readers resolve backticked tokens to verbs, so a backticked `homes` left in
  the ordinary row is itself the partition breach. The verb contrast lives below the table.
- **A new below-table section**, *"The `homes` split"*, carrying both operator grounds, the
  `doctor --repair` shape and why it is load-bearing, four derived-not-asserted measurements, and
  the `init --home` residual.
- **No fenced block added.** MEASURED: `grep -c '^```' docs/specs/multi-fleet.md` is **0** before
  and after, and the file is still in `tests/test_receipts.py`'s `UNENFORCED` set. E5's measured
  4-tests-RED trap was not tripped.

### The three test files (+333 / −22)

`tests/test_terminal_surface.py` — `DESTRUCTIVE_VERBS` gains the two flagged tokens, discharging
the landing obligation the ruling named (the file the 2026-08-05 landing missed).

`tests/test_round7_defect_pins.py` — `RATIFIED_*` tuples moved with production, in this commit;
census re-measured (**13 destructive + 7 disruptive + 13 ordinary first-tokens = 33**, from
12/7/14 — the destructive tuple holds 14 tokens but 13 first-tokens); two stale `homes` comment
blocks corrected; a `homes` analogue of the `doctor --repair` lint pin.

`SPEC_TOKEN_FOR` is now **empty**, and pleasingly so: its only entry was `"homes": "homes
--add/--retire"`, justified by *"`homes` has no destructive form to distinguish it from — unlike
`doctor`."* The ruling gave it one, so the divergence dissolved. An empty dict makes
`test_every_declared_divergence_is_LIVE` vacuous, so a 3-case seed now proves that loop still
fires.

**A latent defect in a partition pin, found by being its first exercise.**
`test_no_verb_IS_NAMED_BY_TWO_spec_rows` accumulated a **list** of effects per verb, so two tokens
for one verb in the *same* row read as two rows. `doctor --repair` and `sup-decision --clear` are
one token each and never exposed it. MEASURED: with the correct spec edit in place it failed with
`{'homes': ['destructive', 'destructive']}` — a false positive. Collapsed to a **set** of effects,
which is what the docstring always claimed it asked, and seeded in both directions (a genuine
two-row verb still fires; two tokens in one row do not).

## 5. A-1 — the `max` → `min` proof

**The brief's routing rationale for A-1 does not survive §3, and A-1 does.** The brief sent A-1
here because *"your edit is what changes that — `homes` becomes exactly such a verb"*. Under the
residual shape it does **not**: `homes --add` matches exactly one tier, and `max` of a one-element
list is that element under any comparator. So the pin is built on a **constructed** two-tier verb.
That is not weaker — `max` is a property of the resolver, not of any verb — and it keeps the rule
guarded on a table whose whole design is to avoid two-tier verbs.

`tests/test_verb_effect_guard.py::TestTheWorstMatchingTierWins`:

- `test_the_plant_really_creates_two_matching_tiers` — a seed for the seed, asserting the
  construction really yields two matched tiers. Without it every assertion below could pass for the
  wrong reason, since `max` of one element equals `min` of it.
- `test_a_verb_matching_two_tiers_takes_the_worse` — **3 parametrised rows**
  (ordinary/destructive, ordinary/disruptive, disruptive/destructive). Three rather than one
  because `min` is not the only wrong comparator: an always-`destructive` resolver would satisfy
  row 1 and row 2 catches it.
- `test_the_flag_being_absent_leaves_the_bare_tier` — the bounding direction; deliberately green
  under both comparators.
- `test_the_shipped_table_still_cannot_exercise_this_rule` — A-1's finding as an executable
  statement, with a failure message telling the next reader what to do if a real two-tier verb
  lands.

**The plant, MEASURED.** Byte-level, on the final tree, asserted applied before anything ran
(`b.count(old) == 1`, then re-read from disk and asserted `min` present / `max` absent, CRLF
intact) — the brief noted a silently-refused plant has cost this wave twice.

**RED receipt — full suite, `py -3.13`, mutant on disk:**

```
3 failed, 4133 passed, 14 skipped, 1 xfailed in 373.42s
FAILED ...TestTheWorstMatchingTierWins::test_a_verb_matching_two_tiers_takes_the_worse[ordinary-destructive-destructive]
FAILED ...TestTheWorstMatchingTierWins::test_a_verb_matching_two_tiers_takes_the_worse[ordinary-disruptive-disruptive]
FAILED ...TestTheWorstMatchingTierWins::test_a_verb_matching_two_tiers_takes_the_worse[disruptive-destructive-destructive]
```

*(Transcript excerpt from this lane's run; not a `docs/specs/**` receipt.)*

**Exactly three failures, all of them the new pin.** This re-derives ga3's A-1 finding at my own
tree rather than trusting it: of 4151 tests, nothing else in the suite distinguishes `max` from
`min`. It also shows the pin is not over-broad — the other 4133 are untouched by the comparator.

**Restore proven twice, as the brief requires.** Byte-identically
(`sha256 01ce0fa4052b99e586fb4c31dd1b3586c2bd1174a8be7b6905e14e2a7cded63a`, `sha256sum -c` → `OK`)
**and** by re-running the floor: `4136 passed, 14 skipped, 1 xfailed`.

## 6. Floors — predicted, then measured

**Base re-derived at my own branch point**, `e5889fe`, both interpreters:
`4134 collected → 4119 passed, 14 skipped, 1 xfailed`.

> **A contaminated first attempt, disclosed.** My first `py -3.10` base ran in the background while
> I began editing, and came back `5 failed, 4114 passed, 1 error`. Those six are all source-reading
> pins; the cause was my own concurrent edits, not the tree. I discarded it, stashed the work
> (verifying the tree was clean), re-ran 3.10 with nothing in flight, and restored the WIP with a
> `sha256sum -c` check on all three files. The clean base is the one above. Recording it because a
> reader finding that transcript should know it was contamination and not a red floor.

**Predicted delta: +17**, derived by enumerating the new test functions and their parametrisations
— not by counting `def test_` lines:

| Source | + |
|---|---|
| `test_the_seed_a_dead_divergence_is_caught` (3 params) | 3 |
| `test_the_homes_writes_are_carried_as_the_flagged_spellings` | 1 |
| `test_the_seed_a_verb_in_two_rows_is_still_caught` (2 params) | 2 |
| 3 × new `homes` granularity pins | 3 |
| `TestTheWorstMatchingTierWins` (1 + 3 + 2 + 1) | 7 |
| `test_the_spec_still_lists_each_token_in_its_own_row` — parametrised over ratified tokens, 33 → 34 | 1 |
| **total** | **17** |

**Predicted: `4151 collected → 4136 passed, 14 skipped, 1 xfailed`, both interpreters.**

**MEASURED, by `--collect-only` for the count and a full run for the result:**

| | collected | result |
|---|---|---|
| `py -3.13` | **4151** | **4136 passed, 14 skipped, 1 xfailed** (370.98s) |
| `py -3.10` | **4151** | **4136 passed, 14 skipped, 1 xfailed** (338.85s) |

Prediction exact on both. Long runs were redirected to files, never piped.

---

## WHERE THIS BRIEF WAS WRONG

The brief nominated its two likeliest errors. **One was wrong, one was right**, and there is a
third it did not anticipate.

1. **"The two tokens are sufficient" — WRONG, and the brief called this as its likeliest miss.**
   They are sufficient for the *resolver* (claim 3 re-derives TRUE) and insufficient as a
   *landing*: they put `homes` in two rows and turn two shipped partition pins RED. The landing
   shape is the `doctor --repair` residual — flagged tokens in the destructive tuple, bare verb in
   no tuple, tier declared in `VERB_EFFECT_RESIDUAL`. §3.

2. **"No residual-flags entry is needed" — RIGHT.** `VERB_EFFECT_RESIDUAL_FLAGS` genuinely is not
   needed, for the reason the brief gave: neither flag overrides `dest=`. But note the near-miss in
   the wording — a `VERB_EFFECT_**RESIDUAL**` entry *is* needed, and it is the load-bearing half of
   the landing. The two dicts are one word apart and do opposite jobs.

3. **NOT ANTICIPATED: A-1's routing rationale is void, though A-1 itself is not.** The brief
   asserted *"`homes` becomes exactly such a verb — bare ordinary, flagged destructive"* and built
   the A-1 assignment on it. Under the landed shape `homes` matches exactly one tier per
   invocation, so it does **not** exercise `max`. Had I taken the two-row shape purely to keep that
   rationale alive, I would have traded a fail-safe partition for a fail-open one in order to make
   a mutant redden. The pin uses a constructed verb instead, and
   `test_the_shipped_table_still_cannot_exercise_this_rule` records that the shipped table still
   cannot exercise the rule — which is A-1's finding, now standing rather than latent.

4. **Also not anticipated, and a defect in the repo rather than in the brief:**
   `test_no_verb_IS_NAMED_BY_TWO_spec_rows` counted tokens where it claimed to count classes, and
   `homes` is the first verb with two flagged tokens in one row. It reported a false partition
   breach. Fixed and seeded both ways (§4).

**What no test here can check** is whether the operator's classification is right. This lane
transcribes a ruling and makes it enforceable; the ruling itself is the operator's.
