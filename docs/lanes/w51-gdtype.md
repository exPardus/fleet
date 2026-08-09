# w51-gdtype — third gate on slice (d)'s type-totality fix

**Subject:** `920266c..2cc4410` on `w51/gdtype`, six commits, `bin/fleet.py +104`,
`bin/fleet_statusline.py +93`, `tests/test_statusline_home.py +343`,
`docs/specs/terminal-surface.md +8`, `docs/lanes/w51-dtype.md +809`.
**Scope:** NARROW. Gates `w50-gd` and `w50-gd2` taken as read. The two exploits were not
re-driven, the chain-file move was not re-audited, the migration path was not re-reviewed.

---

## VERDICT

**NOT-GATING.** No BLOCKING finding. One MAJOR, two MINOR.

Nothing in this diff erases the operator's row, raises out of the render, or lets foreign text
through a sanitiser. The MAJOR is that the fix's own chosen defence — exempting fleet's diagnostic
word from the unknown-bucket cap — was applied to one of the **two** fleet-authored words the same
commit introduced, and the docstring that applies it states, as its reason, a claim that is false on
this tree. The pin cited as holding that property is a tautology and does not hold it.

| # | Severity | Finding | Basis |
|---|---|---|---|
| 1 | **MAJOR** | `FIELD_UNKNOWN` (`?`) was left inside the cap that `TYPE_FAULT` (`?type`) was exempted from, in the commit that introduced both. Three foreign statuses sorting below `?` suppress it; `?type` survives the same three. The exemption docstring's stated reason is false three ways, and `test_the_cap_can_hide_only_names_the_attacker_chose` re-asserts `_bucket_order`'s own filter and passes unchanged under the X7 mutant it is cited as covering. | **MEASURED** |
| 2 | MINOR | `_reset_clock`'s stated contract — *"Any other TYPE -> `_safe`'s refusal word"* — is false for five falsy non-string types. The `if not iso` short-circuit sits **above** the `try`, so `0`, `0.0`, `False`, `[]`, `{}` never reach `_safe` and render as `reset?`, byte-identical to a legitimately unset `null`. | **MEASURED** |
| 3 | MINOR | `_safe`'s refusal path ignores `_safe`'s own `limit` parameter: the one branch of a function whose contract is *"bounded"* that is not bounded by the caller's bound. Latent — zero call sites pass `limit` today. | **MEASURED** |

Four things the brief flagged as risks came back **CLEARED**, each attacked with a seeded detector:
Q1's over-refusal (731 benign combinations, 0 erasures), the render's totality (224 field×shape
renders + supervisor + container shapes, 0 raises), the *"zero `except` handlers added"* claim
(true, verified two ways), and the exemption's width cost (bounded at 9 characters, not unbounded in
homes).

---

## Q1 — Does the narrowing OVER-refuse? **CLEARED. It does not.**

The brief's sharpest guess. Driver: `q1_benign.py`, 731 combinations, detector seeded first.

**The population is derived, not invented.** Every `status` string `bin/fleet.py` persists into a
registry record, plus the two the snapshot layer can produce for a record that recorded none:

```
git grep -hoE '"status"\] = "[a-z_-]+"' -- bin/fleet.py | sort -u
  "status"] = "dead"            "status"] = "dead-suspected"   "status"] = "idle"
  "status"] = "interrupted"     "status"] = "limited"          "status"] = "orphan"
  "status"] = "over_ceiling"    "status"] = "withheld"         "status"] = "working"
```

(`orphan` / `withheld` are `_index_entry` shard results at `:19694` / `:19712`, not registry worker
records — checked, not assumed. `attached` and `over_budget` are in fleet's vocabulary and are read
and preserved — `_NATIVE_STICKY` at `:3645`, `cmd_release` at `:8194` — but no shipped path writes
either as a literal today; they are in `_ORDER` regardless, so they never reach the capped region
that Finding 1 is about. The seven that remain are the registry-worker set, and `interrupted` and
`dead-suspected` are the two of them outside `_ORDER` and `_LABEL`.)

Then every field the render reads, at every benign value shape a real home writes: ISO text and
`null` for `limit_reset_at`; `float`, `int` and `None` for `stale_seconds`; integer counters; unicode
names; the empty string; a 60-character name; absent optional keys one at a time; a home mid-write
(every subset of seven keys removed — 128 shapes); and all seven benign supervisor shapes.

**The detector is seeded before it is trusted.** Three erasure shapes, all three seen:

```
== detector self-test ==
  seed1 detected: ERASED -- 2 live workers handed in, 1 counted on the line, no overflow counter
  seed2 detected: ERASED -- roster replaced by a no-roster word
  seed3 detected: RAISED TypeError: boom
  all three seeds detected -- detector is live
```

**Result:**

```
== 731 benign combinations driven ==
NO OVER-REFUSAL FOUND on the benign population.
```

Every fleet-authored status on one line, all ten of them, with the operator's own row intact:

```
[fleet]  work 1  att 1  lim 1 reset?  budget 1  ceiling 1  idle 1  ? 1  dead-suspected 1  interrupted 1  +1 dead
```

**The brief guessed Q1 was the sharp question. It is not.** The narrowing is conservative in exactly
the right direction: `registry_status` returns the value unchanged for every `str`, so no legitimate
status can be refused, and no benign shape of any other field reaches a narrower that could reject
it. The lane's incentive argument was sound and the answer it predicted is the one that holds.

What section 6 of the same driver turned up on the way is Finding 1, below — not an over-refusal,
an under-application.

---

## Q2 — What does the `TYPE_FAULT` cap exemption buy an attacker? **9 characters.**

### The brief's premise is wrong, and it matters

> *"How many `?type` markers can N foreign homes put on one line?"*

**N is always 1.** The statusline resolves exactly ONE home per render and renders exactly one
roster from it — `main` runs `resolve_blob_home`, assigns the single `fleet.FLEET_HOME`, and calls
`render_statusline(fleet.status_snapshot())` once:

```
fleet.FLEET_HOME = decision["home"]
line = render_statusline(fleet.status_snapshot(), color=_want_color())
```

There is no path on which two homes contribute to one line. (Chained delegates print their own rows
*above* fleet's, from their own processes; that is a different axis and a different gate's subject.)

### And within that one home, the answer is one marker, always

Buckets are dict keys, so every wrongly-typed status of every wrong type collapses into one:

```
     1 wrongly-typed rows -> markers=1  line='[fleet]  ?type 1'
     2 wrongly-typed rows -> markers=1  line='[fleet]  ?type 2'
    50 wrongly-typed rows -> markers=1  line='[fleet]  ?type 44  ? 6'
   500 wrongly-typed rows -> markers=1  line='[fleet]  ?type 438  ? 62'
```

### The bytes

Widest line each tree can be driven to, same maximal input (every known bucket occupied and stale,
`limited` carrying its longest clock word, the cap's worth of maximal-length hostile statuses, a
non-zero overflow counter, a dead tail, `sup released` and the `2 bodies` alarm):

| | 920266c (merge base) | 2cc4410 (branch) |
|---|---|---|
| widest, string statuses only | **274** chars | **274** chars |
| the same input plus wrongly-typed rows | **not renderable** — `TypeError: unhashable type: 'list'`, which `main`'s exit-0 guard turns into a blank line (the MAJOR; measured separately at 200 rows) | **283** chars |
| delta attributable to the exemption | n/a | **+9** |

The 9 characters are `  ?type N` — two separator spaces, the five-character word fleet authored, one
space, and the count. The count's digits scale with the number of workers exactly as every other
bucket's do, so the exemption's own contribution is `8 + digits(count)` and nothing else. It is
**bounded, additive, and not a function of the number of homes.** No availability finding here.

**The exemption is not a detail — the brief was right about that — but not for its width.** See
Finding 1.

---

## Q3 — Is the ordering total, and is `_safe`'s refusal reachable?

### Method: AST call graph, not grep

`q3_ast.py` parses `bin/fleet_statusline.py`, builds the intra-module call graph over every
`FunctionDef` (walking nested `Call` nodes, so closures like `paint` count as their enclosing
function's code), and walks forward from every def to the four sinks.

**22 defs. Exactly one entrance — `main`.** Nothing outside this module imports it in production:
`git grep fleet_statusline` outside `tests/` and `docs/` returns only `bin/fleet.py:406`, which
*returns the path* for `init --statusline` to write into `settings.json` and does not import it.

```
--- sink `_bucket` ---            main -> render_statusline -> _bucket
--- sink `_supervisor_chunk` ---  main -> render_statusline -> _supervisor_chunk
--- sink `_safe` ---              main -> render_statusline -> _safe
                                  main -> render_statusline -> _reset_clock -> _safe
```

**Two entries reach `_safe`, and they differ in who narrows.**

* `render_statusline:366` — `_safe(bucket)`. `bucket` comes from `_bucket(w)`, which is
  `fleet.registry_status(worker.get("status"))`, which is **total and always `str`** (17 shapes
  driven, including `bytes` and a bare `object()`; every answer a `str`, every answer hashable).
  So the narrower runs first here and `_safe`'s refusal branch is **unreachable** from this site.
* `_reset_clock:185` — `_safe(iso)` on raw `limit_reset_at`. **Nothing narrows this first;
  `_safe` IS the narrower.** So the block comment's headline — *"THE NARROWING COMES BEFORE THE
  SANITISER"* — is true of `status`, which is what it is about, and is not a property of the module.
  That is not a defect on its own (the refusal fires before any character work), but it is where
  Finding 2 lives.

### The row loop has no subscripts left

The AST reports **zero** `w[...]` loads inside `render_statusline`'s row loop. The five plane-B
sinks the previous gate found are gone; the four remaining `Load` subscripts in that function are
`buckets[bucket]` (key taken from `buckets`' own keys), `_LABEL[bucket]` (guarded by
`bucket in _LABEL`), two `_STATUS_COLOR[<literal>]`, and `sorted(resets)[0]` (guarded by a
non-empty `group`). The loop's own guards, read off the AST:

```
For at line 335: iter=workers
    guard: if not isinstance(w, dict): continue
    guard: if w.get('tier') == 'supervisor' and w.get('status') != 'dead': continue
```

### Does the refusal raise, or return something a caller does not expect?

**No.** `_safe` over 17 shapes returns `'?type'`, type `str`, on every non-`str` and never raises —
including `bytes` and `object()`. The one caller of the reachable refusal (`_reset_clock`) hands it
into a set of strings and an f-string; both want a `str` and get one.

**Totality, driven rather than argued:**

| drive | renders | raised |
|---|---|---|
| every render-read row field × 15 JSON shapes, + each field deleted | 224 | **0** |
| every supervisor field × 15 shapes, + `supervisor` itself of 15 shapes | 75 | **0** |
| the `workers` container of 19 shapes (incl. tuple, generator, set, dict) | 19 | **0** |

Non-list containers degrade to `[fleet]: no workers`; a list of non-dict rows degrades to
`[fleet]  no live workers`. Both are words, neither is silence.

### *"Zero `except` handlers added"* — VERIFIED, two ways

```
=== except handlers added by 920266c..2cc4410 (bin/ tests/) ===
  +except lines: 0
  -except lines: 0

=== except handlers per tree, by AST ===
  920266c bin/fleet_statusline.py      except=11 try=11
  2cc4410 bin/fleet_statusline.py      except=11 try=11
  920266c bin/fleet.py                 except=275 try=250
  2cc4410 bin/fleet.py                 except=275 try=250
```

**And the brief's warning was right while its location was wrong.** A refusal *can* widen the
swallow without an `except` — and one does, in Finding 2 — but it is not in a handler. It is the
`if not iso: return ""` short-circuit sitting **above** the `try` block, which returns before any
narrowing or sanitising happens at all.

---

## FINDING 1 — MAJOR — the exemption was applied to one of two sibling words, and its stated reason is false

**MEASURED.**

`c551a4d` introduces two fleet-authored words for a registry field the schema did not get, and its
own comment insists they are different facts:

```python
TYPE_FAULT = "?type"      #: the field's TYPE is not the schema's
FIELD_UNKNOWN = "?"       #: "...and when the field is absent or null, which is a different fact"
```

It exempts **one** of them from the unknown-bucket cap, and gives this reason:

> *"`fleet.TYPE_FAULT` IS NOT CAPPED EITHER, and it is not in `_ORDER`. **It is the one bucket name
> in the unknown region that FLEET authors — every other one is a string out of a foreign
> registry.** Left in the capped set it could be pushed off the line by three hostile statuses that
> merely sort earlier, so a foreign home could suppress the very word that says its own record is
> malformed."*

### The claim is false on this tree, three ways

```
  '?type'            in _ORDER=False  in _LABEL=False  exempt_from_cap=True
  '?'                in _ORDER=False  in _LABEL=False  exempt_from_cap=False
  'interrupted'      in _ORDER=False  in _LABEL=False  exempt_from_cap=False
  'dead-suspected'   in _ORDER=False  in _LABEL=False  exempt_from_cap=False
```

`?` is authored by `registry_status` **in the same function, in the same commit**. `interrupted` is
written by `cmd_interrupt` into `data["workers"][name]["status"]` and saved (`bin/fleet.py:8134`,
under `fleet_lock()`, followed by `save_registry(data)`); it has its own shipped verb and its own
slash command. `dead-suspected` is written by the liveness recompute (`bin/fleet.py:3710`). Neither
is in `_ORDER` or `_LABEL`, so both sit in the capped region the docstring says only an attacker can
occupy.

### The exploit the exemption exists to stop, still live on the sibling

`?` is ASCII `0x3F`; `_bucket_order` sorts the unknown region and keeps the **first three**. Every
printable ASCII byte from `0x20` to `0x3E` sorts before it and survives `_safe` intact. Three of them
is the whole cost:

```
  no foreign rows      -> [fleet]  work 1  ?type 1  ? 1
  1 foreign status(es) -> [fleet]  work 1  ?type 1  !a 1  ? 1
  2 foreign status(es) -> [fleet]  work 1  ?type 1  !a 1  "b 1  ? 1
  3 foreign status(es) -> [fleet]  work 1  ?type 1  !a 1  "b 1  #c 1  +1 unknown
       `?` bucket present: False   `?type` present: True
```

Same three statuses, same line: **`?type` survives and `?` does not.** That asymmetry is the
finding. A foreign home suppresses the word that says *"this home has records with no status
recorded"* for the price of three status strings, on the one surface the operator reads
continuously, at rc 0 — which is the exemption's own stated threat, on its own sibling constant.

The loss is *declared* but not *named*: the line says `+1 unknown`, a count of buckets, so the
operator cannot tell that the hidden one was fleet's own word rather than a foreign one.

And on a home where fleet's own non-vocabulary statuses are live, the same three push those off too:

```
  +0 earlier-sorting statuses -> [fleet]  work 1  ? 1  dead-suspected 1  interrupted 1
  +1 earlier-sorting statuses -> [fleet]  work 1  !0 1  ? 1  dead-suspected 1  +1 unknown
  +2 earlier-sorting statuses -> [fleet]  work 1  !0 1  !1 1  ? 1  +2 unknown
  +3 earlier-sorting statuses -> [fleet]  work 1  !0 1  !1 1  !2 1  +3 unknown
```

(This second shape needs the hostile statuses in the **same** home as the operator's own workers, so
it is reachable to a compromised worker inside one home rather than to a foreign home across the
resolution — a narrower door than the `?` case above, which needs nothing but the foreign home the
whole slice exists to allow. Both are stated; only the first is claimed as the finding.)

### The pin cited for the property is a tautology, and the mutant it covers is not equivalent

```python
def test_the_cap_can_hide_only_names_the_attacker_chose(self):
    """The exemption stated as the property it buys, and the reason gate
    `w50-gd2`'s X7 equivalence argument survives onto this tree."""
    buckets = {"idle": [], "!a": [], "!b": [], "!c": [], "zzz": [],
               fleet.TYPE_FAULT: []}
    order, hidden = sl._bucket_order(buckets)
    assert fleet.TYPE_FAULT in order, order
    assert hidden == 1
    assert all(b not in ("dead", fleet.TYPE_FAULT) and b not in sl._ORDER
               for b in set(buckets) - set(order))
```

The third assertion re-states `_bucket_order`'s own filter comprehension. `unknown` is *built* as
`b not in _ORDER and b not in ("dead", TYPE_FAULT)`, and `set(buckets) - set(order)` is a subset of
`unknown[3:]`, so the assertion cannot fail for any implementation that keeps the filter — which is
every mutant of the slice. It names the attacker in its title and tests nothing about authorship.

Driven against gate `w50-gd2`'s X7 (keep the **last** three instead of the first three):

```
  SHIPPED (first three)  test_the_cap_can_hide_only_names_the_attacker_chose PASSES=True
      renders: [fleet]  work 1  !x 1  ? 1  dead-suspected 1  +1 unknown
  X7 (last three)        test_the_cap_can_hide_only_names_the_attacker_chose PASSES=True
      renders: [fleet]  work 1  ? 1  dead-suspected 1  interrupted 1  +1 unknown
```

The pin passes on both. **The mutant is equivalent with respect to the suite and not equivalent with
respect to the operator** — it hides a different set of statuses, and on this input it hides the
attacker's and shows fleet's, which is the better behaviour. The exemption is genuinely doing work
(without it, `?type` itself is suppressible), so the lane's *conclusion* is sound; the *argument*
offered for it, and the test offered as its pin, are not.

### Why this is MAJOR and not MINOR

It is not a regression, and the loss is a diagnostic word rather than the operator's roster — both
of which argue down. What argues up is the shape: `docs/lanes/BRIEF-TEMPLATE.md`'s own gate section
names it — *"Ask whether the repair was applied EVERYWHERE the repaired claim appears, not whether
it is correct where it was applied… A repair verified only where it was applied is a repair verified
nowhere."* The exemption is applied at the one site its argument was written at, and the same
argument holds verbatim one constant over, in the same function, in the same commit. Add a false
universal quantifier in the docstring and a tautology as its pin, and the property is not held
anywhere — which is why the X7 equivalence argument that rests on it does not survive contact.

### Remedy (not applied — this lane fixes nothing)

Exempt `FIELD_UNKNOWN` alongside `TYPE_FAULT`, or state in the docstring which fleet-authored names
the cap may hide and why that is acceptable. Replace the tautological assertion with one that
distinguishes the two orderings — e.g. that a roster carrying `FIELD_UNKNOWN` plus three
earlier-sorting foreign statuses still renders `FIELD_UNKNOWN`.

---

## FINDING 2 — MINOR — `_reset_clock` is not total over types, and its docstring says it is

**MEASURED.** The docstring added by `c551a4d`:

> *"Any other TYPE -> `_safe`'s refusal word, because `limit_reset_at` is only text by convention."*

```
  str-ok       -> '14:20'      type=str
  int          -> '?type'      type=str
  int-zero     -> ''           type=str   <<< NON-STRING that did NOT get the refusal word
  float-zero   -> ''           type=str   <<< NON-STRING that did NOT get the refusal word
  bool-false   -> ''           type=str   <<< NON-STRING that did NOT get the refusal word
  list-empty   -> ''           type=str   <<< NON-STRING that did NOT get the refusal word
  dict-empty   -> ''           type=str   <<< NON-STRING that did NOT get the refusal word
  none         -> ''           type=str
```

`if not iso: return ""` sits above the `try`, so five falsy non-strings return before `_safe` is
reached. Rendered:

```
  limit_reset_at=none         -> [fleet]  lim 1 reset?
  limit_reset_at=list-empty   -> [fleet]  lim 1 reset?
  limit_reset_at=dict-empty   -> [fleet]  lim 1 reset?
  limit_reset_at=list         -> [fleet]  lim 1 resets ?type
```

`limit_reset_at: []` and `limit_reset_at: null` render **byte-identical bytes** — the P1-13 property
this slice has already spent a MAJOR on, and precisely the distinction `FIELD_UNKNOWN`'s own comment
calls *"a different fact"*. Small blast radius: the word is `reset?`, which is honest about not
knowing, and no attacker text reaches the screen. It is the docstring's universal quantifier that is
wrong, and the ordering claim with it.

---

## FINDING 3 — MINOR — the refusal is the one unbounded branch of a bounded function

**MEASURED.** `_safe(text, limit=_FIELD_LIMIT)` promises *"Bounded, with `~` marking the cut"*. The
refusal added by `c551a4d` returns before the bound is consulted:

```python
if not isinstance(text, str):
    return fleet.TYPE_FAULT          # 5 chars, whatever `limit` said
```

`_safe(x, limit=3)` returns a 5-character string. Latent: `grep -rn "_safe(" bin/ tests/` finds no
call site that passes `limit` — the only occurrence of the word is the signature itself — so this is
a trap for the next caller rather than a live defect. Filed because `_safe` is now the module's
declared single place *"that decides what a wrong-typed field looks like"*, and a second caller with
a tighter bound is exactly what that centralisation invites.

---

## Q4 — The merge price, re-derived

### `main` moved a FIFTH time, and slice (e) landed

The brief states `main` is `5cb0e4e` and that it moved four times. At the time of this run:

```
git rev-parse --short main
  75aa4eb

git log --oneline 5cb0e4e..75aa4eb
  75aa4eb merge(w51): slice (e) -- and a whole-file rewrite of the homes list that survived the suite
  2e3e44d docs(w51-slicee): the final floors -- second prediction, also hit exactly
  0117b83 test(w51/slicee): the canary asserted B unchanged without asserting A ran
  ebf823a docs(w51-slicee): two defects in my own report, found self-auditing
  47700d8 test(w51/slicee): GREEN -- the conftest redirect, and the floors
  438ef52 test(w51/slicee): the four §7 pins slice (a) did not ship, RED
```

Everything below is measured at **`main = 75aa4eb`**, `w51/gdtype = 2cc4410`,
`merge-base = 4d78f6c`.

### The control, first, non-zero

```
# main=75aa4eb  w35/nd4c=1e810f7  merge-base=0726914
git merge-tree $(git merge-base main w35/nd4c) main w35/nd4c | grep -cE '^\+?<<<<<<<'
  25
git merge-tree $(git merge-base main w35/nd4c) main w35/nd4c | grep -c '<<<<<<<'
  26
```

Anchored **25**, unanchored **26** — the one-hit gap the template documents (a prose line in
`knowledge/INDEX.md` quoting the marker). Command, commit and number quoted together, per the
amendment. This is my own number at my own base; it agrees with the supervisor's 25 and not with
gate `w51-glaunch2`'s 26, and I make no claim about which of those two ran what.

### The subject pair

```
# main=75aa4eb  w51/gdtype=2cc4410  merge-base=4d78f6c
git merge-tree 4d78f6c main w51/gdtype | grep -cE '^\+?<<<<<<<'
  12
git merge-tree 4d78f6c main w51/gdtype | grep -c '<<<<<<<'
  12
```

**12 conflicts, anchored and unanchored agreeing** (this diff quotes no markers in prose). All 12
are in `bin/fleet.py`; every other path merges clean or is added on one side only.

### Lost-hunk check — digit-masking `:NNNN` **and** `:NNNN-NNNN`

Each conflict's two sides, with `:\d+(?:-\d+)?` replaced by `:N`, compared line for line:

```
  conflict  1: our=6ln their=6ln identical-after-masking=True
  conflict  2: our=1ln their=1ln identical-after-masking=True
  conflict  3: our=1ln their=1ln identical-after-masking=True
  conflict  4: our=2ln their=2ln identical-after-masking=True
  conflict  5: our=1ln their=1ln identical-after-masking=True
  conflict  6: our=1ln their=1ln identical-after-masking=True
  conflict  7: our=4ln their=4ln identical-after-masking=True
  conflict  8: our=2ln their=2ln identical-after-masking=True
  conflict  9: our=2ln their=2ln identical-after-masking=True
  conflict 10: our=2ln their=2ln identical-after-masking=True
  conflict 11: our=1ln their=1ln identical-after-masking=True
  conflict 12: our=1ln their=1ln identical-after-masking=True

  conflicts that are NOT citation-only after masking: 0
  distinct `:NNNN` tokens inside the conflicted regions: 58
```

**0 functional overlap, 0 lost hunks.** The line counts match on both sides of all twelve, so no
hunk is being traded away by either resolution. The lane's read-only price of *12, all
citation-only, 0 functional overlap* **survives `main` moving twice more** — same number at a
different base.

### Is a fourth self-citation re-pin pass owed? **Yes — 31 to 36 of 42.**

Measured, not estimated. A merged `bin/fleet.py` was built read-only with `git merge-file -p`
(no ref moved, no merge performed), the branch's tree materialised beside it with `git archive`, and
the repo's **own** citation pins run against it:

```
merged bin/fleet.py: 21666 lines (branch 21549, main 21570), 0 residual conflict markers, parses OK

py -3.13 -m pytest tests/test_self_citations.py -q
  5 failed, 12 passed
    TestEverySelfCitationResolves::test_no_citation_points_at_a_blank_line
    TestEverySelfCitationResolves::test_every_cited_line_carries_its_anchor
    TestEverySelfCitationResolves::test_every_cited_line_is_inside_the_function_it_names
    TestEverySelfCitationResolves::test_every_function_qualified_citation_lands_in_that_function
    TestEverySelfCitationResolves::test_every_enumeration_matches_the_derived_set

  e.g. quarantine-artifact readers: cited [3157, 4071, 6975, 10826, 11934, 12472, 16165,
       16444, 16601], but the source has [3157, 4071, 6987, 10877, 11985, 12523, 16282,
       16561, 16718]
```

Counting individual citations rather than pins, over the module's own `BY_CITATION` map:

| conflicts resolved to | citations in `bin/fleet.py` | **stale after the merge** |
|---|---|---|
| the branch's side (`--theirs`) | 42 | **36** |
| `main`'s side (`--ours`) | 42 | **31** |

So the pass is owed whichever way the twelve are resolved, and its size is **31–36 citations across
roughly fourteen citing lines** — larger than the 12 conflicts suggest, because most stale citations
are on lines only *one* side touched and therefore merge clean while pointing at the wrong line.
Six of the 42 survive a branch-side resolution and eleven survive a `main`-side one; `:3157` and
`:4071` survive both, being citations into a region neither side moved.

**The merge is cheap and the re-pin is not free.** Budget the fourth pass before landing, and re-run
`tests/test_self_citations.py` on the merged tree rather than on either parent — neither parent's
run predicts it.

---

## FLOORS — PREDICTED IN `a0887a6`, WITH NO RESULTS IN THAT COMMIT

The prediction below was written and committed before a single `pytest` invocation on this
repository. Results were added afterwards, in this commit.

**Prediction: `4489` collected → `4474` passed / `14` skipped / `1` xfailed / `0` failed, on
`py -3.13` and on `py -3.10`, both with and without this file in the tree.**

**Why this file adds zero collected tests.** The brief warns that a docs-only change can move the
floor, and names `CHECK_COUNT_DOCS`, *"derived as every tracked `*.md` minus a dated-history
exemption"*, with *"two pins parametrised over it"*. **No such symbol exists in this tree** — the
only `_CHECK_COUNT` is `tests/test_doc_claims.py:226`, a regex over the phrase *"N checks"*, not a
file set. The real mechanism is `tests/test_receipts.py`:

* `SPEC_DIR = REPO / "docs" / "specs"` (`:113`)
* `_all_specs()` → `sorted(SPEC_DIR.glob("*.md"))` (`:172`), filtered to the enforced set by
  `_is_enforced` (carries a `# at <sha>` pin)
* **three** `@pytest.mark.parametrize("path", _specs())` sites (`:246`, `:619`, `:646`) — not two

So a file added under **`docs/specs/`** and carrying a pin costs **three** collected tests, not two;
a file added under **`docs/lanes/`** — which is where this brief itself orders the verdict — costs
**zero**. The other document-parametrised pins are over fixed tuples (`ENTRY_DOCS`, six entries;
`SURFACES`, three), neither derived from a glob. The lane's own report is the empirical control: it
re-floored at 4489 with `docs/lanes/w51-dtype.md` in the tree.

**Hygiene, asserted before the runs.** No mutant is on disk: every mutation in this gate
(`_bucket_order` → X7, three erasure seeds) was applied by in-process monkeypatch inside scratch
scripts under the job directory and reverted in the same process; the repository tree was never
patched. `git status --porcelain` was empty at the start of every run.

### RESULTS — prediction met exactly, on both interpreters

Round 1, at `a0887a6` (this file present, carrying the prediction and no results):

```
py -3.13 -m pytest --collect-only -q     ->  4489 tests collected in 5.54s
py -3.13 -m pytest -q                    ->  4474 passed, 14 skipped, 1 xfailed in 432.05s

py -3.10 -m pytest --collect-only -q     ->  4489 tests collected in 8.83s
py -3.10 -m pytest -q                    ->  4474 passed, 14 skipped, 1 xfailed in 397.28s
```

**4489 / 4474 / 14 / 1 / 0, four runs, two interpreters — and the "+0 collected" prediction for a
`docs/lanes/` file is what those 4489s confirm.** The brief's independent claim of *"+124 pins"* is
confirmed too, by collecting the merge base in an extracted tree: `920266c` → **4365**, branch →
**4489**, delta **+124**.

Digest bracket on the `py -3.13` round:

```
before: 364b5403119c839f27cbf1e370d98d08e1c95a88497432f4c9970c6a48abd76f  files=245
after : 364b5403119c839f27cbf1e370d98d08e1c95a88497432f4c9970c6a48abd76f  files=245
git status --porcelain -> empty
```

**AND THE `py -3.10` ROUND'S DIGEST BRACKET IS VOID, BY MY OWN HAND.** I edited this file — the
`WHERE THIS BRIEF WAS WRONG` section and two corrections — while that run was in flight, so the
after-digest differs from the before-digest for a reason that has nothing to do with the run. The
instrument did exactly what it exists to do: it refused to certify a run it could not isolate.
`files=` was unchanged at 245 and `git status --porcelain` named only this file, which is
suggestive and is *not* what the bracket claims, so the bracket is reported as void rather than
explained away. Round 2 below re-establishes it on a frozen tree.

### Round 2 — re-floored with this report, results and all, in the tree

*(Results for round 2 are appended by the commit that follows this one; the tree they were run
against is the one this paragraph is committed in.)*

---

## WHERE THIS BRIEF WAS WRONG

The brief asked to be corrected with a receipt. Six places.

**1. `main` is `75aa4eb`, not `5cb0e4e` — it moved a FIFTH time, and slice (e) has already
landed.** The brief opens with *"Slice (d) is one gate from landing. Slice (d) done leaves only
slice (e)"*; by the time this ran, slice (e) was merged to `main` and slice (d) was the outstanding
one. Receipt in Q4 above. Every Q4 number here is at `75aa4eb`; none of the brief's are.

**2. Q2's premise assumes a line that does not exist.** *"How many `?type` markers can N foreign
homes put on one line?"* presupposes a multi-home render. There is none: `main` resolves one home,
assigns one `fleet.FLEET_HOME`, and calls `render_statusline(fleet.status_snapshot())` once. N is
always 1, and the marker count is 1 regardless of rows or types because buckets are dict keys —
measured at 1, 2, 50 and 500 wrongly-typed rows. The follow-up *"if the answer is unbounded in the
number of homes, that is an availability finding"* is therefore unreachable. The bounded answer is
+9 characters.

**3. The floor mechanism the brief names does not exist.** *"`CHECK_COUNT_DOCS` is derived as every
tracked `*.md` minus a dated-history exemption, and two pins are parametrised over it."* There is no
`CHECK_COUNT_DOCS` in this tree; the only `_CHECK_COUNT` is a regex over the phrase *"N checks"* at
`tests/test_doc_claims.py:226`. The real mechanism is `tests/test_receipts.py` — **three**
parametrize sites over `SPEC_DIR.glob("*.md")` with `SPEC_DIR = docs/specs`. So the multiplier is
three per enforced spec, not two, and the scope is `docs/specs/` only. A verdict filed where this
brief itself orders it (`docs/lanes/`) moves the floor by **zero**. The instruction *"if you add
files, predict accordingly"* is right; following the mechanism as written would have produced the
wrong prediction.

**4. The brief's own guess about which question is sharp is wrong, and it guessed that too.** It
says *"Likeliest [wrong]: that Q1 is the soft question (I think it is the sharp one)"*. Q1 is the
soft one: 731 benign combinations, zero over-refusals, with the detector seeded first. The
narrowing is conservative in the right direction by construction — `registry_status` returns every
`str` unchanged, so no legitimate status can be refused. The sharp question was Q2, which the brief
listed among the things it expected to be told were details.

**5. …but its instinct about the swallow was right, and its location wrong.** *"'zero `except`
handlers added' settles the swallow question when a refusal can widen it without an `except`."* The
claim is true (verified two ways) and it does not settle it — Finding 2 is a widening with no
`except` involved. It is not in a handler at all: it is the `if not iso: return ""` short-circuit
sitting **above** the `try` block, which returns before either narrowing or sanitising happens.

**6. What the brief got right, said plainly.** The lane's read-only price of *12 conflicts, all
citation-only, 0 functional overlap* re-derives to exactly 12 at a base two `main` commits later,
with 0 lost hunks — the brief was right to ask for it again and right that it would hold. The
*"+124 pins"* figure is confirmed independently (`4365` collected at `920266c`, `4489` on the
branch). The anchored-grep, control-first and pin-your-control instructions all did work here. And
the exemption is *not* a detail — the brief flagged that correctly, though for the wrong reason:
its cost is nine characters, and its defect is the sibling constant it was not applied to.

**One thing this gate did not do, and says so.** Finding 1 is not a regression — driven at
`920266c`, `?` was already a capped bucket suppressible by the same three statuses. This branch
does not make it worse; it introduces the doctrine that says it should not be true, applies that
doctrine to one of two words, and states a reason for the split that the tree contradicts. That is
what keeps it MAJOR rather than BLOCKING, and it is why this gate does not hold the branch.
