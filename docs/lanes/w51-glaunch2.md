# `w51-glaunch2` — second gate on `w50/launchfix`: the DISCHARGE, and the landing

| | |
|---|---|
| Under gate | `w50/launchfix` @ `168b608`, range **`4a62e21..168b608`** — the discharge of gate `w50-glaunch` (`a9a2975`). Nobody had reviewed it. |
| NOT under gate | the Part-1 statusline fix. `git diff 4a62e21..168b608 -- bin/fleet.py` is **EMPTY** (verified, §1.2), so the first gate's clearance carries. |
| Lane | Gate. Worktree `C:/proga/fleet-w51-glaunch2`, branch `w51/glaunch2` @ `168b608`. |
| Fence held | Commits to `w51/glaunch2` only. No push, no merge in this repo, no other ref moved. **No `fleet` verb was run at all this turn**, so the `FLEET_HOME`-is-not-a-fence hazard was never reached. |
| Interpreters | `py -3.13` and `py -3.10`, both floors re-run **by me, from fresh clones** (§4). |
| Rehearsal | `w50/launchfix` → `main` @ **`7b2ff75`**, in a throwaway clone (§5). |

## 0. VERDICT — **GATING**

**The Part-1 fix should land. The discharge should not land as it stands** — and the reason is
narrow, cheap, and exactly the class the first gate gated on.

Gate `w50-glaunch` returned GATING on *three shipped STATEMENTS, none of them in `bin/fleet.py`*.
The discharge repaired those statements **at the site the gate quoted, and left the same claims
standing at a second site in the same file.** `tests/test_doc_claims.py` now contains, 328 lines
apart:

- **L94** — *"this docstring shipped `94 hits across 21 files`"*, presented as a corrected error, and
- **L422** — *"Measured at w50, the exempt set holds **94 hits across 21 files**"*, the disproven
  number, still stated as a measurement.

and, 20 lines apart:

- **L425** — `docs/NEXT-SESSION.md` named as one of the exempt *"working ledgers"*, and
- **L445** — *"`docs/NEXT-SESSION.md` … is NOT current-tree exempt any more"*, which **this same
  commit** made true.

That is F1 half-discharged and F6 falsifying its own file — the defect shape of F2 (*"this branch
made two of its clauses false"*), reproduced inside the commit discharging F2. Four MAJORs, seven
MINORs, **zero BLOCKING**. Everything else the brief asked me to attack came back sound:

| | | |
|---|---|---|
| **BLOCKING** | — | none |
| **MAJOR** | M1 | `tests/test_doc_claims.py:422` still ships `94 hits across 21 files` — the number F1 exists to retract |
| | M2 | `tests/test_doc_claims.py:425` and `:185` still name `docs/NEXT-SESSION.md` as exempt; F6 moved it into the held population in the same commit |
| | M3 | F3's shape derivation is sound and IS a superset — but the carve-out census it ships is **still incomplete**: **7 of 9 planted mutants escape silently**, 5 of them through shapes the census does not disclose, and the docstring's *"Every entry below is now PINNED by a test"* measures **2 of 5** |
| | M4 | F5's `-z` fix omits `encoding=`, so `_tracked_markdown()` mangles any **non-ASCII** path — and F5's own new pin then fails with a message naming the **wrong cause** (*"the split must be on NUL"*, when the split is already on NUL) |
| **MINOR** | m1 | F6's exemption argument censuses `docs/OPERATOR-GATES.md` as *"two check-count hits"*; under the census's own summed definition it carries **three** |
| | m2 | §7.5.1's *"Hit on every field"* counts `4305 collected`, which was **measured in the predicting commit** — 4 of 5 fields were genuinely at risk, not 5 |
| | m3 | `§7.7` was inserted **above** `§7.6`, so the report now reads 7.5.1 → 7.7 → 7.6 |
| | m4 | CONTRIBUTING.md:41's new *"**28 files today**"* is a bare present-tense count of a derived, moving population, **pinned by nothing** — the exact defect class F1 is about |
| | m5 | `test_doc_claims.py:186` says *"These **five** are the files"*; `len(ENTRY_DOCS)` is **6**, and the CONTRIBUTING.md sentence this discharge rewrote says *"the **six** `ENTRY_DOCS`"* |
| | m6 | the derivation's third name, `bin/fleet_statusline.py:36`'s `_INSTALL_ROOT`, is **inert**: that file has **zero** command renders, so the superset adds no coverage today |
| | m7 | the `INSTALL_ROOT = Path("/opt/fleet")` line added to `test_a_shell_sink_is_censused_even_with_one_path` is **not load-bearing** — the census is identical with and without it |

**Nothing here touches `bin/fleet.py`, and nothing here is a reason to hold the one-line quoting
fix.** M1/M2 are comment edits. If the operator wants the launch blocker gone today, landing
Part 1 and fixing M1/M2/M4 on top is a defensible sequence; my objection is to landing the
discharge *while it still states the things it was written to retract*.

## 1. Fence, subject, and the one claim I took as read

### 1.1 Fence — MEASURED

```
# at 168b608
git rev-parse --abbrev-ref HEAD   ->  w51/glaunch2
git rev-parse --short HEAD        ->  168b608
git status --porcelain            ->  (empty)
```

Every mutant in this report ran in a throwaway `git clone` of `C:/proga/claude-fleet/.git`, never
in this worktree, and every mutant run asserts `git status --porcelain` is empty afterwards or
stops. Clones used: `q1..q5` under the job tmp dir, discarded with the job.

### 1.2 The Part-1 fix is byte-identical across the discharge — MEASURED

```
# at 168b608
git diff 4a62e21..168b608 -- bin/fleet.py    ->  (no output, rc=0)

git diff --stat 4a62e21..168b608
 CONTRIBUTING.md                        |   2 +-
 docs/lanes/w50-launchfix.md            | 255 ++++++++++++++++++++++++++++++++-
 tests/test_doc_claims.py               | 120 ++++++++++++++--
 tests/test_rendered_command_quoting.py | 198 +++++++++++++++++++++----
 4 files changed, 528 insertions(+), 47 deletions(-)
```

So the first gate's *"the Part-1 fix is sound and should land"* carries unchanged, and I did not
re-review it. **Two of those four files are instruments**, which is where this report spends itself.

## 2. Q1 — F3 replaced an instrument. Is the replacement sound, or merely bigger?

**Both. It is sound where it fires, it is a genuine superset, and the census it ships alongside is
still wrong in the same direction the census it replaced was wrong.**

### 2.1 The derivation returns exactly what the lane says — MEASURED, by execution

`_module_scope_path_names()` over the real code plane, with line numbers and the bound expression:

```
# at 168b608
bin/fleet.py             FLEET_HOME     L86    = Path(os.environ['FLEET_HOME']) if … else …
bin/fleet.py             INSTALL_ROOT   L114   = Path(__file__).resolve().parent.parent
bin/fleet_statusline.py  _INSTALL_ROOT  L36    = Path(__file__).resolve().parent.parent
bin/hooks/postcompact_journal.py   []
bin/hooks/posttooluse_mailbox.py   []
bin/hooks/stop_mailbox.py          []
bin/hooks/stop_outcome.py          []
```

Three names, exactly the three claimed, and **nothing it should not return** — no name that merely
looks path-shaped. The code plane is `(REPO/"bin").rglob("*.py")` = 6 files; I derived that
population rather than trusting the docstring, per wave 46.

### 2.2 "Strict superset" — MEASURED behaviourally, not just by name

I restored the old `_PATH_GLOBALS` behaviour (monkeypatching `_directly_path_valued` to accept the
two names, and disabling both new derivations) and diffed the census output:

```
IN OLD BUT NOT NEW (would refute 'strict superset'): []
IN NEW BUT NOT OLD:                                  []
bare INSTALL_ROOT/FLEET_HOME Name uses per file vs derived roots:
  fleet.py: uses=['FLEET_HOME','INSTALL_ROOT'] derived_roots=['FLEET_HOME','INSTALL_ROOT'] UNCOVERED=[]
```

**No regression.** The claim holds — and it holds in the way that matters, which is that no
expression the allowlist saw is now invisible. I checked the specific regression vector too: nothing
in `bin/**` obtains those names by `from fleet import …`, which the derivation (Assign/AnnAssign
only) would not see.

**m6 — but the third name buys nothing today.** `bin/fleet_statusline.py` contains **17** f-strings
and **zero** censused command renders; `_INSTALL_ROOT` is referenced only at L36–37. The docstring's
*"so a command render in that file interpolating it was invisible"* describes a render that does not
exist. The superset is real; its coverage gain is currently zero.

### 2.3 Mutants against the derivation — 7 of 9 SILENT ESCAPES — MEASURED

Planted into `bin/fleet.py`'s source and re-run through the module's own two shipped assertions
(`test_the_census_finds_exactly_the_renders_it_is_pinned_to`,
`test_every_censused_render_quotes_every_path_it_interpolates`). Baseline unmutated: both GREEN.

```
# at 168b608
mutant                                                         census  quote    verdict
CONTROL-A  direct Path() render, one path, `command` sink      RED     RED      CAUGHT
CONTROL-B  module-scope alias the lane just closed             RED     RED      CAUGHT
MUT-1  module-scope ALIAS OF INSTALL_ROOT (one derived step)   GREEN   GREEN    *** SILENT ESCAPE ***
MUT-2  two aliases of INSTALL_ROOT, rule (ii) shape, no sink   GREEN   GREEN    *** SILENT ESCAPE ***
MUT-3  module-scope path binding inside `if`                   GREEN   GREEN    *** SILENT ESCAPE ***
MUT-4  tuple-target module-scope path binding                  GREEN   GREEN    *** SILENT ESCAPE ***
MUT-5  attribute form on the imported module (mod.INSTALL_ROOT) GREEN  GREEN    *** SILENT ESCAPE ***
MUT-6  subscript-assignment sink, ONE path                     GREEN   GREEN    *** SILENT ESCAPE ***
MUT-7  str.join over two module-scope paths                    GREEN   GREEN    *** SILENT ESCAPE ***
```

The two controls going RED is what makes the seven GREENs mean something.

**MUT-6 and MUT-7 are DISCLOSED holes** — the census names subscript-assignment sinks and `str.join`,
and the discharge added both. Credit where due: those two escapes are the instrument behaving as
documented.

**MUT-1 through MUT-5 are NOT disclosed anywhere.** And MUT-1 is the one that matters:

```python
_MUT_BIN = INSTALL_ROOT / "bin"          # module scope, one derived step
def _mutant_render():
    return {"command": f"{_MUT_BIN}/fleet.py sup-status"}
```

The module docstring states the property as *"a MODULE-SCOPE name bound to any of those"*.
`_MUT_BIN` **is** a module-scope name bound to a path, and it is invisible, because
`_module_scope_path_names()` calls `_directly_path_valued` on the bound expression and that
predicate no longer recognises a bare `INSTALL_ROOT` (the allowlist that used to make it recognise
one is what F3 deleted). Module-scope resolution is **not transitive**, while local resolution is —
`_local_bindings`/`_path_valued` recurse, `_module_scope_path_names` does not. `INSTALL_ROOT / "bin"`
is the single most idiomatic derived-path shape in this codebase; it is safe inside a function and
invisible one indent-level out.

MUT-3 (binding under `if os.name == "nt":`) escapes because the scan walks `tree.body` only, which
the docstring calls *"Module scope only, deliberately"* — a conditional module-scope binding is
still module scope, and `FLEET_HOME` at L86 is itself conditional, just as a ternary rather than a
statement.

MUT-4 (`A, B = Path(…), 3`) escapes because `[t for t in node.targets if isinstance(t, ast.Name)]`
drops a Tuple target.

Synthetic probes found four more of the same family, none disclosed: a parameter annotated
`pathlib.Path` (dotted), `"Path"` (string annotation) or `Optional[Path]` all escape, because
`_path_annotated_parameters` requires `isinstance(arg.annotation, ast.Name) and .id == "Path"`; so
do a walrus binding and a class attribute.

### 2.4 Over-match — real, but LOUD, so I grade it low

`_directly_path_valued` uses `ast.walk` over the whole bound expression, so a module-scope global
whose initialiser merely *mentions* a path call is claimed as a path:

```
O1: IS_WIN = Path(__file__).resolve().name == "x"   -> claimed path-valued (it is a bool)
O2: DEPTH  = len(Path(__file__).resolve().parts)    -> claimed path-valued (it is an int)
O3: ROOTS  = [Path("a"), Path("b")]                 -> claimed path-valued (it is a list)
O4: TABLE  = {"k": Path("a")}                       -> claimed path-valued (it is a dict)
```

None fires on the shipped tree (§2.1 measured zero false positives, which is true). The failure mode
is not silence, it is **noise**: an over-claim adds a censused site, `EXPECTED_RENDERS` goes RED, and
the person who wrote an unrelated bool global is told their commit broke a quoting pin. This module's
own docstring names that outcome as fatal — *"A census that demanded quotes there would be unshippable
noise, would be suppressed, and would then hold nothing."* Worth knowing; not worth gating on.

### 2.5 The coverage claim — the population, not the docstring — MEASURED

> *"Every entry below is now PINNED by a test in `TestTheCensusCanSeeWhatItClaimsToSee`, so the list
> cannot drift away from the code the way it just did."*

`TestTheCensusCanSeeWhatItClaimsToSee` holds **12** tests. Against the docstring's **five** carve-out
bullets:

| bullet | pinned? | by |
|---|---|---|
| ONE path, no sink, not a `"command"` value | **NO** | nothing constructs it. The nearest test, `test_prose_naming_a_path_is_NOT_a_command`, uses `registry_path()` — **not path-valued in that snippet at all**, so it is green for a different reason and would stay green if rule (ii) were deleted |
| parameter with no `Path` annotation | yes | `test_an_UNANNOTATED_parameter_is_still_invisible` |
| `.format()` / `%` / concat / `str.join` | yes | `test_the_other_render_MECHANISMS_are_still_invisible` |
| subscript-assignment sink | **NO** | — |
| anything outside `bin/**/*.py` | **NO** | — |

**2 of 5.** The report's own §7.3 table is honest about one of these — it says the subscript sink is
*"named in the docstring"*, not pinned. The **shipped instrument's docstring** is the thing that
overstates, and the shipped docstring is what the next reader believes. This is wave 46's lesson
landing again: the pin's population **is** the claim.

**m7.** `test_a_shell_sink_is_censused_even_with_one_path` gained
`INSTALL_ROOT = Path("/opt/fleet")` with a docstring saying it is there *"because this module no
longer carries a list of blessed global names to fall back on"*. Measured — the census is byte-identical
with and without it, because that snippet's path-valued-ness comes from the `-> Path` helper:

```
WITH the module-scope binding   : [('x.py', 5, 'r', ('statusline_script_path()',))]
WITHOUT the module-scope binding: [('x.py', 4, 'r', ('statusline_script_path()',))]
```

`test_a_MODULE_SCOPE_path_alias_is_seen` is the one seed that genuinely discriminates the new
derivation, and it does.

## 3. Q2 — F1: is the reproduced 94 the whole story?

**The 94 reproduces exactly, first try, under three independent spellings of the arrow form. The
lane's account is true. And F1 is still only half-discharged.**

### 3.1 The census re-derived at `4a62e21` — MEASURED, all four numbers hit

Run in a clone checked out at `4a62e21`, importing **that commit's own** `test_doc_claims`, so the
detectors are the ones that shipped there:

```
# at 4a62e21
tracked md = 141   held = 27   exempt = 114
find_check_count_claims + find_pass_fail_totals, over every tracked *.md NOT in CHECK_COUNT_DOCS:
  INCLUDING docs/lanes/w50-launchfix.md : 129 hits / 22 files    (lane claims 129 / 22)  HIT
  EXCLUDING docs/lanes/w50-launchfix.md :  93 hits / 21 files    (lane claims  93 / 21)  HIT
  the report alone carries              :  36                    (lane claims 36)        HIT
```

### 3.2 The exploratory scanner returns exactly 94 — MEASURED

Shipped detectors **plus** a `check count N → M` arrow form, over the exempt set excluding the
report. I tried three different spellings of that arrow so the result could not be an artefact of
guessing the lane's exact regex:

```
# at 4a62e21
A: check\s+count\s+(\d+)\s*(?:->|→|-->)\s*(\d+)   -> 94 hits / 21 files
B: checks?\s+count\s+(\d+)\s*(?:->|→)\s*(\d+)     -> 94 hits / 21 files
C: check[^\n]{0,20}?(\d+)\s*(?:->|→)\s*(\d+)      -> 94 hits / 21 files
   extra hit in all three: docs/reviews/TT-BUILD-REVIEW-SPEC-2026-07-24.md:183  'check count 22 → 23'
```

93 + 1 = 94, and the extra hit is the exact file, line and text the lane named. **The finding
sharpens exactly as the brief predicted**: not a careless digit but *measured with one instrument,
pasted into the docstring of another* — committed one file from the paragraph diagnosing that same
defect in `docs/SPEC.md`'s `grep -c` receipt. The lane's own §7.1 grades it that way and is right to.

### 3.3 Judging "restate with its definition against a named commit" as the remedy

**The reasoning for not pinning it is correct.** A pin over a population that includes the document
stating the pin's own number would go RED on every lane report; that is not a pin, it is a tax. And
`129/22 @ 4a62e21` with the derivation route attached is genuinely re-runnable — I re-ran it above
from the text alone, without asking anyone.

**But it relocates the rot rather than removing it, and the discharge proves that itself.** The
number moved *within this very branch*: measured at `168b608` with the shipped detectors, the same
census is **130 hits / 20 files** including the report (**91 / 19** excluding it). Three commits
later, four of the five digits are different. A named-commit restatement is honest, but its
half-life here is one commit, and nothing tells a reader when it has lapsed.

The structural answer the lane did not take: **make the census a derivation, not a digit** — ship the
route (which it now does) and *delete the numbers*, or emit them from a helper the reader can call.
A number that cannot be pinned probably should not be printed.

### 3.4 M1 — and this is why F1 is not discharged

The repair landed at the top-of-file docstring. **The same file states the disproven number again at
L422, unrepaired**:

```
# at 168b608
git grep -n '94 hits across 21 files'
tests/test_doc_claims.py:94 :        DEFINITION ATTACHED -- this docstring shipped `94 hits across 21 files`
tests/test_doc_claims.py:422:# w50, the exempt set holds 94 hits across 21 files -- lane reports and gate
```

L94 says the file *shipped* that claim, past tense, as the thing being corrected. L422 is that claim,
still shipping, phrased as a measurement (*"Measured at w50, the exempt set **holds** …"*), sitting
directly above `_HISTORICAL_PREFIXES` — i.e. above the definition of the very set it miscounts. A
reader who arrives at `_HISTORICAL_PREFIXES` (the natural entry point when you want to know what is
exempt) reads the retracted number and no retraction.

### 3.5 M2 — F6 falsified two statements in its own file

The same comment block, three lines later:

```
tests/test_doc_claims.py:425:# journal, and the working ledgers (`PLAN-PROGRESS.md`, `NEXT-SESSION.md`).
tests/test_doc_claims.py:445:#   `docs/NEXT-SESSION.md` was on this list beside it and is NOT current-tree
                             #   exempt any more …
```

L425 names `docs/NEXT-SESSION.md` as a member of the exempt set. L445, **twenty lines below, in the
same hunk this commit wrote**, says it is not. Measured at `168b608`: `docs/NEXT-SESSION.md` **is**
in `CHECK_COUNT_DOCS` (held), and `len(CHECK_COUNT_DOCS)` is 28.

L185 carries the same falsification in substance: *"the INTERNAL campaign docs (`PLAN-PROGRESS.md`,
`NEXT-SESSION.md`, …) are working ledgers whose stale numbers are **history rather than defects**"* —
a stale check-count number in `NEXT-SESSION.md` is now a RED test, i.e. a defect.

This is F2's finding — *"this branch made two of its clauses false"* — reproduced inside the commit
that discharges F2. It is also the cheapest thing in this report to fix.

**m1.** The F6 exemption argument (L442–444) censuses `docs/OPERATOR-GATES.md` as *"its **two**
check-count hits … `29 checks` and `23 checks`"*. Under the census definition **this same discharge
wrote down 340 lines above** — `find_check_count_claims` **+** `find_pass_fail_totals` — that file
carries **three**:

```
# at 168b608
docs/OPERATOR-GATES.md   find_check_count_claims -> [23, 29]
                         find_pass_fail_totals   -> [28]
```

The third is the `28 PASS / 0 FAIL` inside the same quoted argument, so **the decision is unaffected
and I agree with it** — all three hits are quotations and holding the file would mean editing a
quotation. But the census supporting the carve-out is wrong about the file it is carving out, which
is the third instance in one discharge of *a census wrong about its own population*.

## 4. Q3 — F8: does git actually witness the ordering?

**Yes for the floor result, no for one of the five fields — and both floors reproduce exactly.**

### 4.1 The ordering is real — MEASURED

`git show 1d1216a` contains the prediction and **no floor results**: grepping it for
`passed|failed|skipped|xfail|rc=` returns only the prediction blockquote itself, the withdrawn
§3 sentence, and prose. The measurements arrive in `83f8b2c`, a later commit. **The ordering is
witnessed by git, not asserted.** F8's repair is real and is the right pattern; I have copied it in
§5 of this report.

**m2 — one field was not at risk.** `1d1216a` also contains

```
py -3.13 -m pytest --collect-only -q   ->  4305 tests collected
py -3.10 -m pytest --collect-only -q   ->  4305 tests collected
```

i.e. `4305 collected` was **measured in the predicting commit**. §7.5.1's table lists it as the first
row of `predicted | measured 3.13 | measured 3.10` and concludes *"Hit on every field"*. Four fields
were genuinely at risk (`passed`, `skipped`, `xfailed`, `failed`); the fifth was a restatement. The
claim is not false, it is inflated by one — which matters only because this is a report about
inflated claims.

### 4.2 Both floors, re-run by me from fresh clones — MEASURED, all fields HIT

Two independent `git clone --no-hardlinks` checkouts at `168b608`, each `git status --porcelain`
empty before the run:

```
# at 168b608
py -3.13 -m pytest --collect-only -q  ->  4305 tests collected
py -3.10 -m pytest --collect-only -q  ->  4305 tests collected
py -3.13 -m pytest -q  ->  4290 passed, 14 skipped, 1 xfailed in 463.47s   rc=0
py -3.10 -m pytest -q  ->  4290 passed, 14 skipped, 1 xfailed in 429.12s   rc=0
```

| field | lane predicted | my 3.13 | my 3.10 |
|---|---|---|---|
| collected | 4305 | **4305** | **4305** |
| passed | 4290 | **4290** | **4290** |
| skipped | 14 | **14** | **14** |
| xfailed | 1 | **1** | **1** |
| failed | 0 | **0** | **0** |

4290 + 14 + 1 = 4305. **No discrepancy in either direction.** The floor the lane reports about itself
is the floor an independent checkout produces.

## 5. Q4 — THE LANDING REHEARSAL, at `main = 7b2ff75`

### 5.1 `7b2ff75` IS journal-only — PROVED, not assumed

```
# at 7b2ff75
git show --stat 7b2ff75
 supervisor/JOURNAL.md | 110 ++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 110 insertions(+)
```

One file, +110, no deletions. **But the rehearsal is not therefore a formality**, and the reason is
not the last commit — it is the twelve before it. `main` has moved **12 commits** off this branch's
base `4d78f6c`, touching **19 files**, and the intersection with this branch's 7 files is exactly
`bin/fleet.py` — the file this branch changes. That is what has to be re-measured, and the
journal-only tip does not weaken it.

### 5.2 The conflict instrument, calibrated against a known non-zero input FIRST — MEASURED

A conflict count whose good answer is `0` proves nothing until it has produced a non-zero on
something. `w35/nd4c × main` @ `7b2ff75`:

```
# live: a merge rehearsal in a throwaway clone; the answer depends on today's main
merge rc=1, 6 conflicted files
ANCHORED   grep -cE '^\+?<<<<<<<'  total = 26
UNANCHORED grep -c   '<<<<<<<'     total = 31
per-file divergence (anchored vs unanchored):
   docs/NEXT-SESSION.md   1 vs 2
   knowledge/INDEX.md     1 vs 3
   knowledge/lessons.md   1 vs 3
```

The instrument is **non-vacuous**, and the anchoring is **load-bearing**: unanchored over-counts by
5 across 3 files, because `knowledge/INDEX.md` and `knowledge/lessons.md` quote the marker inside
the wave-42 lesson *about marker-grep nulls*, and `docs/NEXT-SESSION.md` quotes it once more.

### 5.3 The merge — AUTO-MERGES CLEAN — MEASURED

```
# live: a merge rehearsal in a throwaway clone against main @ 7b2ff75
merge-base main w50/launchfix = 4d78f6c
files main touched since base   = 19
files branch touched since base = 7
touched by BOTH                 = bin/fleet.py

git merge --no-commit --no-ff w50/launchfix
   Auto-merging bin/fleet.py
   Automatic merge went well; stopped before committing as requested
   rc=0
git ls-files -u                     ->  (empty)
ANCHORED conflict-hunk total        ->  0     (instrument calibrated at 26 above)
merged tree                         ->  54ea03a19db51172f0584455ff18fb662a178b2f
```

`bin/fleet.py` **auto-merges**: the one-line quoting change and main's edits are disjoint hunks.

### 5.4 The lost-hunk check — NO LOST HUNKS — MEASURED, and my first instrument was broken

Digit-masked for `:NNNN` **and** `:NNNN-NNNN`. Comparison done by exact string membership in Python,
so a line beginning `- ` is never parsed as a flag — the `grep -Fqx` hazard is avoided by
construction rather than by care.

```
MAIN   (4d78f6c -> 7b2ff75)               : 5318 added lines checked, 0 LOST   (19 files)
BRANCH (4d78f6c -> w50/launchfix)         : 1965 added lines checked, 0 LOST   ( 7 files)
TOTAL                                     : 7283 added lines checked, 0 LOST
CONTROL — absent lines the check must SEE:
  'ZZZ-sentinel-that-is-not-in-the-tree'            detected-as-missing=True
  '- ZZZ-dashed-sentinel-that-is-not-in-the-tree'   detected-as-missing=True
  '# ZZZ-non-ascii-sentinel §—→ not in the tree'    detected-as-missing=True
CONTROL — present lines it must NOT report missing:
  plain line / line starting `- ` / line carrying non-ASCII    all found=True
```

**The first run of that check reported 1030 lost lines, and every one was false.** Cause:
`subprocess.run(..., text=True)` without `encoding=` decodes git's stdout with the Windows ANSI
codepage, while `Path.read_text(encoding="utf-8")` decodes the file correctly — so every added line
containing `§`, `—`, `→` or `×` mismatched. **My control passed the whole time**, because my
sentinels were ASCII. That is wave 38's lesson, verbatim, committed by the person quoting it: *a
control must include the SHAPE of the data, not merely an instance.* The control above now carries
all three shapes. It is also **the same defect as M4**, found independently, twenty minutes apart, in
two different instruments — which is the strongest evidence I have that M4 is worth fixing.

### 5.5 Tree-did-not-move digest — the "before" reading

Content digest over bytes on disk, **not** `git write-tree` (which hashes the index, is silent on
unstaged changes, and cannot fail). Checkout-relative — compared only against itself, in this one
working tree. For tree identity I use `git rev-parse HEAD^{tree}` instead.

```
m-before     files=247 tree_sha256=1e68415c7ec3dd59a26d11836fc36f4e6ebe758809b40a3d8a88b1efee276719
merged commit 9963167   parents 7b2ff75 168b608   tree 54ea03a1…   status: 0 dirty lines
```

### 5.6 THE MERGED-TREE FLOOR — PREDICTION, and this section contains no results

Inputs, all measured before this prediction was written, none of them a floor:

```
# at 4d78f6c   py -3.13 -m pytest --collect-only -q  ->  4238 tests collected
# at 7b2ff75   py -3.13 -m pytest --collect-only -q  ->  4250 tests collected
# at 168b608   py -3.13 -m pytest --collect-only -q  ->  4305 tests collected
# at 168b608   py -3.10 -m pytest --collect-only -q  ->  4305 tests collected
```

main added **4250 − 4238 = 12** tests; this branch added **4305 − 4238 = 67**. The merge is clean and
the two sets are disjoint, so:

> **PREDICTION — merged tree `54ea03a1`, on BOTH `py -3.13` and `py -3.10`:**
> **4317 collected, 4302 passed, 14 skipped, 1 xfailed, 0 failed.**
> Derivation: `4238 + 12 + 67 = 4317` collected; `4290 + 12 = 4302` passed; the skip and xfail sets
> are predicted **unchanged** at 14 and 1. `4302 + 14 + 1 = 4317`.
>
> **Unlike §7.5, the `collected` field here IS at risk**: I have deliberately NOT run
> `--collect-only` on the merged tree, so all five fields are predictions and none is a restatement
> of a measurement in this commit. The two standing assumptions are named so they can fail
> visibly: that main's 12 added tests all PASS, and that they add no skip and no xfail.
>
> If it misses, it is reported as a miss and the prediction is not adjusted.

**This commit contains no floor results.** The numbers land in the next commit, so git witnesses the
ordering rather than this report asserting it.

## 6. Q5 — what did the discharge ARM?

The discharge touched `CONTRIBUTING.md` and two test modules. **A test module is an instrument, and
one of the two armed a new failure with a remedy that names the wrong cause.**

### 6.1 M4 — F5's `-z` fix mangles non-ASCII paths, and F5's own pin misdiagnoses it

`_tracked_markdown()` at `168b608`:

```python
proc = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=REPO_ROOT,
                      capture_output=True, text=True)      # <-- no encoding=
```

`-z` disables git's path quoting, so non-ASCII paths arrive as raw UTF-8 bytes and `text=True`
decodes them with the Windows ANSI codepage. Mutants in a throwaway clone at `168b608`, each
restored and asserted clean before the next:

```
# at 168b608
CONTROL  docs/My Notes.md        (ASCII, has a space)  ->  73 passed              GREEN
SUBJECT  docs/Unicode-Nötes.md   (non-ASCII, NO space) ->  3 failed, 70 passed    RED
SUBJECT  docs/Ünicode Notes.md   (non-ASCII + space)   ->  3 failed, 70 passed    RED

E  AssertionError: 'docs/Unicode-NÃ¶tes.md' is not a file -- `_tracked_markdown()` mangled a
   path. `git ls-files` does not quote spaces; the split must be on NUL.
```

**The control is green, so F5's stated fix works for its stated case.** The subject is red, and the
message is wrong twice over: the split *is* already on NUL, and the failing path contains **no
space**. A contributor who follows that remedy finds the NUL split already in place and has no next
step. This is the shape the campaign already has a name for — a permanently-red row whose remedy
would not fix it — and it is armed by the pin added to *detect* mangled paths.

It also mangles the **parametrisation**: the two parametrised tests run against
`docs/Unicode-NÃ¶tes.md`, a path that does not exist, so the real file's content is never read. That
is the identical defect F5 was raised about, one layer down.

Severity: latent today (no tracked markdown carries a non-ASCII filename), loud when it fires,
wrong when it speaks. One keyword fixes it.

### 6.2 What the discharge did NOT arm — MEASURED, and this is the good news

**F4's narrowing costs nothing on the held population.** I re-ran the pre-F4 regex against the
post-F4 one over all 28 held files and diffed the claim sets per file:

```
# at 168b608
held population = 28 files
(no held file's claim set changed)
exempt set: old-regex=81 hits, new-regex=79 hits, delta=-2
```

So `(?<![\d.#])` and the horizontal-whitespace narrowing removed **two** hits, both in exempt files,
and made **no real claim invisible in any held document**. F4 is sound.

**F6 costs nothing today.** `docs/NEXT-SESSION.md` measures `find_check_count_claims -> []` and
`find_pass_fail_totals -> []`, so moving it into the held population arms no immediate RED — exactly
as the discharge says.

**F3 stranded nothing.** `_PATH_GLOBALS` has no surviving code reference; the four hits are all
prose describing its removal.

**F2's repair is genuinely caught by its own pin.** `CONTRIBUTING.md` is held and measures
`find_check_count_claims -> []` / `find_pass_fail_totals -> []` — the examples really are written
with `N` rather than digits.

**m4.** But the rewritten sentence introduces a *new* unheld number: *"`CHECK_COUNT_DOCS`, derived as
every tracked `*.md` minus a pattern-based dated-history exemption — **28 files today**"*. Measured,
28 is correct. It is also a bare present-tense count of a **derived, moving** population, pinned by
nothing (`test_the_check_count_population_is_derived_and_split_correctly` asserts only
`10 < len(docs) < len(tracked)`), in a file that **is** held — and this very discharge moved that
number from 27 to 28. It is F1's defect class, freshly planted, in the discharge of F1.

**m5.** `tests/test_doc_claims.py:186` says *"These **five** are the files whose job is to be true for
a stranger"*; `len(ENTRY_DOCS)` is **6**. Pre-existing, but F2 is precisely *"the shipped description
of this pin's scope is wrong"*, and the discharge rewrote the CONTRIBUTING.md half to say *"the
**six** `ENTRY_DOCS`"* while leaving the module's own comment saying five.

### 6.3 Reachability across a trust boundary — nothing found

Slice (d)'s gate found working cross-home exploits. I looked for the analogue and found none: this
discharge adds no code path, no `fleet` verb, no file write, no env-var read, no subprocess except
the `git ls-files` above, and touches nothing under `bin/`. The two test modules are read-only over
the repo. **The only thing it made reachable is a test failure (§6.1); the only thing it made
harder to measure is its own census (§3.4, §3.5, m1).**

## 7. WHERE THIS BRIEF WAS WRONG

Four, and the third is the one worth the most.

1. **"The script is in `docs/lanes/BRIEF-TEMPLATE.md`."** — FALSE at `168b608`. That file is **80
   lines** and contains no digest script; `git grep -l tree_sha256` over the tracked tree returns
   exactly one file, `docs/lanes/w50-launchfix.md`. I wrote my own (§5.5). **The script IS on `main`**
   — `7b2ff75:docs/lanes/BRIEF-TEMPLATE.md` has 74 added lines including *"Proving a run changed
   nothing — NOT with `git write-tree`"*. So the brief was describing a file that exists on the
   branch it is dispatching *against*, not on the branch it dispatched *me to*. The instruction was
   right about `main` and wrong about my cwd, which is wave 38's finding wearing a third costume.

2. **"The campaign quoted 26 for `w35/nd4c × main` since wave 38; the true value is 25, the extra hit
   being `knowledge/INDEX.md`."** — not reproducible as stated, and it cannot be, because the value
   is a function of `main`. Measured against `main @ 7b2ff75` I get **anchored 26, unanchored 31**,
   with prose markers in **three** files, not one (`knowledge/INDEX.md` **2**, `knowledge/lessons.md`
   **1**, `docs/NEXT-SESSION.md` **1**, and one more from the anchored/unanchored split). The brief
   hands a control value with no commit attached — which is the same defect the brief itself
   diagnoses two paragraphs earlier. The *method* is right and I used it; the *number* is a receipt
   without a pin.

3. **"F3's shape derivation is the safe half and F1 the interesting one (I suspect the reverse)."** —
   **the brief's suspicion is right, and still understates it.** F1 came back fully reproducible on
   the first attempt, in three spellings (§3.2); there is nothing left to find in the digit. F3 is
   where the mutants land: 7 of 9 silent escapes, 5 undisclosed, and a coverage claim that measures
   2-of-5. But the brief frames this as F3-vs-F1, and the real answer is neither — **the biggest
   finding in this report (M1/M2) is in the part of the discharge the brief did not ask about at
   all**: whether the repairs were applied everywhere the repaired claim appears. Five questions, and
   the defect was in the sixth.

4. **"That `7b2ff75` is journal-only and therefore the rehearsal is a formality"** was listed as a
   likely error, and it is — but not for the predicted reason. `7b2ff75` **is** journal-only (§5.1).
   The rehearsal still matters because `main` moved **12** commits and **19** files off this branch's
   base, intersecting it at `bin/fleet.py`. The staleness the brief warns about is real; the tip
   commit is just not where it lives.

**Where the brief was right and it mattered:** "re-run it yourself" on the 94 (it reproduced, which
*changed the grade* from BLOCKING to sharpened-MAJOR); "plant mutants against the derivation itself"
(seven escapes); "run your measurement against a known non-zero input first" (26 before 0);
"watch for lines beginning `- `" (I avoided that one and then hit a *different* control defect in
the same instrument, §5.4).

## 8. What this gate did NOT do

- **Did not re-review the Part-1 fix.** Byte-identical, verified once (§1.2), clearance taken as read.
- **Did not fix anything.** Findings, not repairs — no change to `bin/fleet.py`, `CONTRIBUTING.md`,
  or either test module on this branch.
- **Did not run any `fleet` verb**, so nothing in this report depends on `FLEET_HOME` fencing.
- **Did not measure `main`'s own floor.** §5.6's prediction assumes main @ `7b2ff75` is green on its
  own; if the merged floor misses, that is the first thing to check.
- **Did not close the census holes I found.** MUT-1..MUT-5 are reported, not patched.
- **Did not run the merged floor on a second clone per interpreter** — both interpreters run against
  the one merged checkout, sequentially, with the digest re-read between them.
