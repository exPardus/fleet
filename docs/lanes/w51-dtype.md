# w51-dtype — the statusline render made total over field TYPES

**Subject:** `w51/dtype`, branched from `w50/gd2` @ `920266c` (which contains `w50/d` @ `5a47819`
plus that gate's verdict — `git merge-base --is-ancestor w50/d w50/gd2` returns 0, MEASURED).
**Discharges:** gate `w50-gd2`'s single MAJOR, its mutant X4, its X7 equivalence question, and the
third self-citation re-pin pass.
**Fence held:** commits on `w51/dtype` only. No push, no merge, no other ref moved.

Every line below is tagged **MEASURED** (a command was run and its output is pasted or counted) or
**BELIEVED** (reasoning I did not drive).

---

## 0. FLOOR PREDICTION — WRITTEN BEFORE THE FLOORS WERE RUN

**REVISED ONCE, BEFORE ANY FLOOR RAN, AND THE REVISION IS DISCLOSED HERE RATHER THAN HIDDEN.** The
first prediction (`c551a4d`, 4483) was made when this branch carried 118 new tests. The mutant sweep
then found a survivor on code *I* had added this branch — the non-dict worker-row guard, R9 in §8 —
so I closed it with six more tests. **No floor had been run at that point**, and the revised
prediction below is committed in a commit that carries no floor result either. A prediction revised
before the instrument runs is a prediction; one revised after is an adjustment, and the brief calls
that a STOP-and-report event. This is the first kind, and the git history shows which.

| | predicted |
|---|---|
| collected, `py -3.13` | **4489** |
| collected, `py -3.10` | **4489** |
| passed | **4474** |
| skipped | **14** |
| xfailed | **1** |
| failed | **0** |

**Where 4489 comes from.** The base at `920266c` collects **4365** — MEASURED on an extracted copy
of that commit, and equal to the number gate `w50-gd2` §7.4 reported, so the base is agreed rather
than assumed. This branch adds **124** collected tests, counted as parametrize PRODUCTS rather than
as `def test_` lines (32 defs were 42 tests once, and that gap was the whole distance between two
predictions being credible):

| class | tests | how |
|---|---|---|
| `TestAForeignHomeCannotEraseTheOperatorsRow` | 89 | 10 + 1 + 1 + (10×2) + (5×10) + 1 + 1 + 5 |
| `TestTheNarrowingComesBeforeTheSanitiser` | 16 | 1 + 1 + 1 + 10 + 1 + 1 + 1 |
| `TestTheTierFieldIsTotalToo` | 13 | 10 + 1 + 1 + 1 |
| `TestTheOverflowCounterIsRenderedInColour` | 6 | six unparametrized |
| **total** | **124** | |

`4474 + 14 + 1 = 4489`. Skipped and xfailed are predicted UNCHANGED: nothing here adds a skip, an
xfail or a platform guard. The spec paragraph (`1e5dd66`) adds no collected test.

**RESULT: see §9.**

---

## 1. SAFETY — WHY I WAS CONTAINED, NOT MERELY THAT I WAS

**Every `fleet` invocation I ran, and which home it touched — MEASURED.**

| command | how many | which home |
|---|---|---|
| `bin/fleet.py home` | 3 (one per revision under test) | the temp sandbox home — it printed that path, and it is the GATE the rest of the run was conditioned on |
| `bin/fleet.py status` | 6 | the temp sandbox home |
| `bin/fleet.py status --all` | 3 | the temp sandbox home |
| `bin/fleet.py doctor` | 3 | the temp sandbox home |
| `bin/fleet_statusline.py` (as a subprocess) | 12 | the temp sandbox home, or the temp foreign home the sandboxed homes-list named |
| `fleet init`, `fleet init --statusline`, `fleet homes --add` | **0** | — |

**Why containment held, not merely that it did.** Three mechanisms, and the third is the one the
`FLEET_HOME IS NOT A FENCE` stanza exists for:

1. `USERPROFILE`, `HOME`, `HOMEDRIVE` and `HOMEPATH` were redirected into a temp fake home in every
   child environment. On Windows `Path.home()` resolves through `ntpath.expanduser`, which reads
   `USERPROFILE` first — and **both** files fleet can touch outside a home derive from
   `Path.home()`: `homes_list_path()` directly, and `statusline_chain_path()` through
   `user_settings_path()`. Redirecting the home redirects both by construction.
2. `INSTALL_ROOT` is `Path(__file__).resolve().parent.parent` with **no env override by design**
   (`bin/fleet.py:106` says so explicitly), so a step-4 install-root fallback resolves to whichever
   throwaway tree the child was started from. Setting an `INSTALL_ROOT` env var would have been
   theatre; I removed it from the harness for that reason.
3. **`CLAUDE_CODE_SESSION_ID` was removed from every child environment.** This lane is a
   fleet-launched session, so its own sid is in the live registry; left in place, §5 step 2 would
   outrank step 3 and resolve the live home no matter what `FLEET_HOME` said. `assert
   "CLAUDE_CODE_SESSION_ID" not in env` runs before every spawn.

**And the population was not empty by accident.** Wave 48's audit came back clean for the wrong
reason — `~/.claude/fleet-homes.list` did not exist, so the lookup population was empty. Mine is a
positive containment: the sandboxed list **exists, inside the fake home, and names two temp homes**,
so the resolution had a real population to work on and still could not reach the live home, because
the list it read was not the live one.

**The gate, asserted rather than assumed — MEASURED:**

```
MERGE BASE 4d78f6c   fleet home -> C:/Users/Techn/.claude/jobs/3e4357c5/tmp/verbs/home  (== temp home, normalised)
BRANCH     920266c   fleet home -> C:/Users/Techn/.claude/jobs/3e4357c5/tmp/verbs/home  (== temp home, normalised)
FIXED      worktree  fleet home -> C:/Users/Techn/.claude/jobs/3e4357c5/tmp/verbs/home  (== temp home, normalised)
```

Compared NORMALISED (`fleet home` prints `as_posix()`); a literal compare against a Windows path
would have failed on the separators and looked like a breach that is not one.

**Both ends of every driver — MEASURED:**

```
[safety before] ~/.claude/fleet-homes.list exists: False
[safety before] ~/.claude/fleet-statusline-chain.json exists: False
[safety before] ~/.claude/settings.json mtime: 1786210442854189800
...
[safety after]  ~/.claude/fleet-homes.list exists: False
[safety after]  ~/.claude/fleet-statusline-chain.json exists: False
[safety after]  ~/.claude/settings.json mtime: 1786210442854189800
```

`1786210442854189800` ns is `2026-08-08 22:34:02`, before this session began. **The chain file this
branch introduces is ABSENT on the real machine at the end of the run**, as it was for `w50/d`, and
§9 re-asserts it after the full floor.

---

## 2. THE MAJOR — REPRODUCED FOUR-CELL, THEN CLOSED

### 2.1 The four cells, actual rendered bytes — MEASURED

Fixture, identical in every cell: a fake `~` whose `.claude/fleet-homes.list` names `homeGOOD` and
`homeEVIL`; `$FLEET_HOME` = `homeGOOD`, whose worker is `working` and claims nobody; `homeEVIL`
claims the blob sid. The two homes render **different** benign words so the receipt says which home
was read rather than resting on a coincidence — and `homeEVIL` carries a delegate of its own, which
must never run.

```
  homeGOOD (operator's own, $FLEET_HOME) renders `work 1`
  homeEVIL (foreign, claims the blob sid)  renders `idle 1` when benign

MERGE BASE 4d78f6c | benign foreign home        rc=0 fleet row: True  op delegate: 1 evil delegate: 0 out='[operator-statusline]\n[fleet]  work 1\n'
MERGE BASE 4d78f6c | hostile-typed foreign home rc=0 fleet row: True  op delegate: 1 evil delegate: 0 out='[operator-statusline]\n[fleet]  work 1\n'

BRANCH     920266c | benign foreign home        rc=0 fleet row: True  op delegate: 1 evil delegate: 0 out='[operator-statusline]\n[fleet]  idle 1\n'
BRANCH     920266c | hostile-typed foreign home rc=0 fleet row: False op delegate: 1 evil delegate: 0 out='[operator-statusline]\n'

FIXED      tree-fix | benign foreign home        rc=0 fleet row: True  op delegate: 1 evil delegate: 0 out='[operator-statusline]\n[fleet]  idle 1\n'
FIXED      tree-fix | hostile-typed foreign home rc=0 fleet row: True  op delegate: 1 evil delegate: 0 out='[operator-statusline]\n[fleet]  ?type 1\n'
```

Row 2 against row 4 is the gate's delta and it reproduces exactly. Row 3 is worth naming
separately: `work 1` → `idle 1` is the **home actually moving**, so the benign cell is not passing
because the resolution failed to fire.

### 2.2 The displacement direction, which the first gate found and the brief before it missed

`op delegate: 1` and `evil delegate: 0` on **every** row, including the merge base and including the
fix. The operator's own delegate row is present exactly once and `homeEVIL`'s never ran: the fix
closes a disappearance **without** re-opening a displacement. That is asserted per-cell rather than
inferred, because "the row is there" and "the row is the operator's" are different claims and gate
`w50-gd` measured only the first.

A pin holds the same property from the other end
(`test_a_foreign_home_cannot_push_the_fault_word_off_the_line`): nine hostile statuses that sort
before `?type` render `?type 1  !hostile-0 1  !hostile-1 1  !hostile-2 1  +6 unknown` — the fault
word cannot be pushed off the line by names the attacker chose.

### 2.3 The systematic type-fuzz — the instrument gate §10 said it did not build

Gate `w50-gd2` §10: *"Whether MAJOR 1 has siblings. I found two unhashable sinks by driving seven
field shapes. A systematic type-fuzz of every registry field is the right instrument and I did not
build one."* Built. Three planes, because the two sinks are in two files and only one is downstream
of the other; every field × 18 JSON shapes × two base statuses (`idle` and `limited`, so
`_reset_clock` and `_limit_reset_passed` are actually entered — a fuzz that never reaches a branch
reports a clean sheet for code it did not execute).

**BEFORE, at `920266c` — MEASURED:**

```
=== A. registry record -> status_snapshot -> render_statusline ===
  (14 rows, all `status` x unhashable)   combinations=684  NOT-ok=14
        -> TypeError at fleet.py:5543 by_status[status] = by_status.get(status, 0) + 1

=== B. hand-built snapshot row -> render_statusline ===
  status          list/dict          -> TypeError at fleet_statusline.py:287 buckets.setdefault(_bucket(w), []).append(w)
  status          <<absent>>         -> KeyError   at fleet_statusline.py:172 if worker["status"] == "idle" and worker["mail"]:
  mail            <<absent>>         -> KeyError   at fleet_statusline.py:172
  limit_reset_at  <<absent>>         -> KeyError   at fleet_statusline.py:324 resets = {_reset_clock(w["limit_reset_at"]) for w in group}
  resume_eligible <<absent>>         -> KeyError   at fleet_statusline.py:326 if any(w["resume_eligible"] for w in group):
  stale_seconds   any non-number     -> TypeError  at fleet_statusline.py:320 if stalest and min(stalest) > stale_after:
  stale_seconds   <<absent>>         -> KeyError   at fleet_statusline.py:319
  combinations=648  NOT-ok=45

=== C. the supervisor claim file (inside the resolved home) ===
  combinations=58  NOT-ok=0
```

**AFTER — MEASURED:**

```
=== A ===  combinations=684  NOT-ok=0
=== B ===  combinations=648  NOT-ok=0
=== C ===  combinations=58   NOT-ok=0
TOTAL NOT-ok: A=0 B=0 C=0
```

Three results in that table are worth naming rather than summing:

- **Plane A has exactly ONE sink.** `status_snapshot` reads eleven record fields and only `status`
  can raise, because everything else is already funnelled through a coercer that never raises
  (`_registry_cost`) or through a `try` that catches the right exceptions (`_parse_iso`,
  `_limit_reset_passed`). The MAJOR has **no sibling in that function** — MEASURED over 684
  combinations, not argued.
- **Plane B is five times worse and is the plane the shipped tests use.** Every hostile-status test
  in §7 of `tests/test_statusline_home.py` hands `render_statusline` a hand-built row. A fix
  confined to `bin/fleet.py` would have left all five open — which is what the gate meant by *"a
  second sink one file over, reached if the first is ever fixed alone"*, and it is worse than the
  gate knew: it is five, not one. Four of the five are KeyErrors on an ABSENT key, a shape the gate
  did not drive.
- **Plane C was already closed and I did not have to touch it.** `_supervisor_tier_snapshot` answers
  from a fixed four-word vocabulary and wraps everything in a bare `except Exception`, so no claim
  file — including a 400-deep one, a list, a string and unparseable bytes — can produce a
  wrongly-typed `state`. Gate §10 named this as the next surface to fuzz; it is fuzzed and it is
  clean. I hardened `_supervisor_chunk` anyway, as a fail-closed default for the next caller, and
  say plainly that it closes nothing reachable today.

### 2.4 The verb surface has no sibling either — MEASURED

A verb resolves through the same §5 step 2, so `fleet status` can also be pointed at a foreign home.
Driven on all three revisions against a sandbox home holding `status: "idle"`, `status: ["idle"]`
and `status: {"a": 1}` side by side:

```
    fleet status         rc=0   fleet status --all   rc=0   fleet doctor   rc=1 (its own health rows)
```

No crash on any revision. **Stated narrowly:** the status table re-derives its status column from a
liveness probe in this fixture, so it does not read the raw field the way the statusline does — this
is evidence that the verb surface does not share the defect, not evidence that it renders the raw
value safely.

---

## 3. THE FIX, AND WHY `str()` IS THE WRONG ONE — MEASURED, AND THE BRIEF'S REASON IS NOT MINE

### 3.1 What changed

| where | what |
|---|---|
| `bin/fleet.py` | `TYPE_FAULT = "?type"`, `FIELD_UNKNOWN = "?"`, and `registry_status(value)` — total over every JSON value, returns `str`, never `str()`-coerces |
| `bin/fleet.py` `status_snapshot` | `status = registry_status(rec.get("status"))` — narrowed, not defaulted |
| `bin/fleet_statusline.py` `_safe` | **refuses** a non-string (returns `fleet.TYPE_FAULT`) instead of opening with `str(text)` |
| `_bucket` | narrows through the same helper; `.get` instead of `[...]` |
| `_supervisor_chunk` | `state` narrowed to `str`, `age` narrowed to a number |
| `_live_supervisor_bodies`, the row loop | non-dict rows skipped; `snap.get("workers")` |
| the stale filter | `isinstance(s, (int, float))` instead of `is not None` — `is not None` tested the wrong property, it admitted every non-null type there is |
| `_bucket_order` | `TYPE_FAULT` exempt from the unknown cap |

**The exit-0 swallow was not widened.** No `except` clause anywhere on this branch catches more than
it did at `920266c`; the diff adds zero `except` handlers. That was the brief's first constraint and
it is checkable straight from the diff.

### 3.2 Which comes first, and why — the answer the brief asked for

**The narrowing comes first; the sanitiser comes second.** A sanitiser is not a validator, and
`_safe`'s guarantees are all about *characters* — printable ASCII, bounded to 24, brackets
neutralised. It has no guarantee about *structure*. So the type is narrowed to a word **fleet
authors** before any sanitiser sees the value, and `_safe` answers a non-string with that same word
rather than trying to be a validator on the way past.

**The brief's stated reason for rejecting `str()` is WRONG, and I measured it.** The brief says
`str(["idle"])` is *"a bracket-bearing attacker-chosen string arriving after the point where
brackets get neutralised"*. It does not arrive after. `_safe` stringified **first** and neutralised
**second**, so the brackets were always neutralised:

```
  _safe(['idle'])   = "('idle')"
  _safe({'a': 'b'}) = "{'a': 'b'}"
  _safe([['x']])    = "(('x'))"
```

(Note the braces survive — `_safe` neutralises `[`/`]` because they are the *nameplate's* syntax,
and never claimed to do more.)

**Three reasons that do hold, in descending order of how much they matter:**

1. **`str()` re-opens P1-13 one field over — MEASURED.**

   ```
   status=['idle']   -> _safe -> "('idle')"
   status="['idle']" -> _safe -> "('idle')"
   ```

   A malformed record and a record forging that repr render **identical bytes** on the one surface
   the operator reads continuously. That is exactly the property this slice already spent a MAJOR
   on, and re-opening it would be worse than the crash, because a crash is at least visible once.
   `?type` is fleet's word and no attacker input produces it except by writing the literal string —
   the already-graded forgery class of gate §4.3, which costs the attacker nothing and buys them
   nothing.

2. **`str()` is unbounded work to print 24 characters — MEASURED.**

   ```
   str, 6 chars         str()+_safe     0.014 ms  | narrow-first   0.002 ms
   str, 100k chars      str()+_safe     9.649 ms  | narrow-first   8.897 ms
   list of 20k ints     str()+_safe    14.733 ms  | narrow-first   0.003 ms
   list of 200k ints    str()+_safe   148.789 ms  | narrow-first   0.004 ms
   dict of 50k keys     str()+_safe    75.186 ms  | narrow-first   0.003 ms
   ```

   149 ms per refresh, on a surface that refires after every assistant message, chosen by whoever
   wrote the foreign registry. The MAJOR is an availability finding; a fix that hands the same
   attacker a linear-in-file-size cost per refresh is the same finding with a different symptom.

3. **`str()` destroys the distinction the surface is required to keep.** `?type` and `?` are
   different words because *"the field is of the wrong shape"* and *"nothing was recorded"* are
   different facts. `str()` answers both with text and neither with a diagnosis.

**One argument I expected to hold and it does NOT — stated because I looked.** I expected a nesting
depth that PARSES but cannot be `str()`-ed from inside the render's call stack, which would have
made `str()` non-total as well as wrong. There is no such depth:

```
  depth   900..2000: registry ok=True  rendered '[fleet]  lim 1 resets ((((((((((((...'
```

`json.loads` accepts 2000-deep arrays and `str()` survives all of them. **`str()`-coercion would
have been total.** It is rejected for the three reasons above and not for that one.

### 3.3 Why `?type` is not in `_ORDER`, and why it is exempt from the cap

`_ORDER`, `_LABEL` and `_STATUS_COLOR` are the vocabulary of statuses **fleet writes into a
registry**. Nothing ever writes `?type` to disk; it is a render-time substitution, exactly like
`_reset_clock`'s fallback, so it lives on the unknown-bucket path and is capped, sanitised and
coloured by the same rules as any status fleet did not write. Adding it to `_ORDER` would put a word
into the "statuses fleet writes" set that fleet never writes.

It is nonetheless **exempt from the unknown cap**, and that is not a contradiction: it is the one
name in the unknown region that fleet authors, and every other one comes out of a foreign registry.
Left in the capped set, three hostile statuses sorting before `?` (`!a`, `!b`, `!c`) would suppress
the word that says the foreign record is malformed — a foreign home silencing fleet's own
diagnosis, which is the MAJOR again in miniature. §4 records what that exemption does to X7.

---

## 4. THE TWO SURVIVING MUTANTS

*(filled in at §8 — the sweep's receipts.)*

---

## 5. THE THIRD RE-PIN PASS — 31 MOVED, CONTENT-VERIFIED, 0 DEFECTS

`bin/fleet.py` goes 21485 → 21549 lines, **+64**, all at one insertion point plus a two-line comment.
The re-pin driver reuses `tests/test_self_citations.py`'s **own** classifier verbatim — `:(\d+)`
inside a COMMENT or non-f-string STRING, minus timestamps and other-document references — rather
than writing a second regex, because a second regex is how wave 45 found 16 of 31.

**MEASURED:**

```
base HEAD: 21485 lines   working tree: 21549 lines   delta +64
self-citations found: 42  by shape: {'bare': 37, 'named': 4, 'range': 1}
citations whose NUMBER moves: 31
  line    911  bare    :10762  ->  :10826
  ...
  line   8975  range   `cmd_respawn:8502-8504`  ->  `cmd_respawn:8566-8568`
  line  15042  bare    :8876  ->  :8940          <- FOUR bare numbers in one comma list
  line  15042  bare    :9196  ->  :9260
  line  15042  bare    :9477  ->  :9541
  line  15042  bare    :9695  ->  :9759
  ...
range citations validated end >= start: 1
WROTE bin/fleet.py (31 citations repointed)
```

**Both wave-45 traps were handled by construction, not rediscovered.** The comma-list shape appears
at lines 15042/15043/15058/15059/15749/15750 and the driver sees every number in it because it uses
the oracle's regex. The range END carries **no colon**, so a colon-keyed scan cannot see it at all —
matched first, both ends mapped, and `end >= start` validated **before** anything was written.

**FIXPOINT is a census, not a red/green read.** A pin file reports its FIRST failure per test, so one
green run is a lower bound. The independent verifier enumerates all of them:

```
base HEAD lines=21485  tip lines=21549
self-citations checked (range ENDS included): 43
  1. out of range .................... 0
  2. pointing at a blank line ........ 0
  3. cited line has no base image .... 0
  4. CONTENT DIFFERS base vs tip ..... 0
  5. ranges (1) with end<start or an end outside its function: 0
  6. IDEMPOTENCE: citations a SECOND driver run would move: 32
DEFECTS: 0
```

Check 4 is the one a survived double-shift fails: the **text** of every cited line is byte-identical
at the base and at the tip. Check 6 is the measurement behind *"do not run the driver twice"* — a
second run would move 32 more numbers, all of them wrongly. **The driver runs once; the ORACLES are
what run to fixpoint**, and they are green:

```
tests/test_self_citations.py        17 passed
tests/test_retired_sid_citations.py  4 passed
tests/test_doctrine_citations.py     9 passed
tests/test_doc_claims.py            26 passed
tests/test_round7_defect_pins.py    63 passed
tests/test_pin_usage_contract.py    51 passed
                                   170 passed
```

**A FOURTH pass is still owed and this branch cannot make it.** §5 of `w50-d` and §8 of `w50-gd2`
are about the **post-merge** tree, and my fence forbids the merge. Priced read-only below.

---

## 6. THE MERGE WITH `main`, PRICED READ-ONLY — `main` HAS MOVED TWICE MORE

`main` was `4d74d22` when the gate first measured, `c6ddf0f` when it committed, and is **`7b2ff75`**
(`2026-08-09 14:40:03 +0500`, *"docs(w50): journal the wave-50 landings, corrections and
stand-down"*) now. Say what `main` was, because the claim rots the next time it moves.

`git merge-file` on the three blobs — **no ref moved, no merge performed** — MEASURED:

```
base 4d78f6c   mine c551a4d   main 7b2ff75
files this branch touches: [bin/fleet.py, bin/fleet_statusline.py, docs/lanes/w49-dcap.md,
  docs/lanes/w50-d.md, docs/lanes/w50-gd2.md, docs/lanes/w51-dtype.md,
  docs/specs/terminal-surface.md, tests/test_statusline_home.py, tests/test_terminal_surface.py]
files shared with main:    [bin/fleet.py]

bin/fleet.py: mine 17 hunks x main 27 hunks -> 15 overlapping ranges, 19 base lines
  of those, carrying a `:NNNN` citation: 19
  NON-citation overlapping lines ......: 0
  git merge-file predicts 12 conflict block(s); CITATION-ONLY: 12; other: 0
```

**A caveat about my own instrument, disclosed because it nearly shipped wrong.** My first
classifier masked `:\d{3,5}` and reported **1 non-citation conflict**. Printing the block rather
than trusting the count showed why: the block differed only in `cmd_respawn:8566-8568` vs
`:8521-8523`, and the range END carries no colon, so the mask left `-8568` standing. **The wave-45
blind spot, reproduced inside the tool built to avoid it** — caught only because the driver prints
what it classifies. Fixed to `[:-]\d{3,5}`; the corrected count is 12/12 citation-only.

**So a fourth re-pin pass is required post-merge**, on the same terms `w50-d` §21 gives: take either
side's text, re-derive a difflib map against the merge base, run the pin files to fixpoint, no
constant delta, do not run the driver twice. Note also that `main` has touched
`tests/test_self_citations.py`, so the oracle itself moves with the merge.

---

## 7. WHAT THE FIX DOES **NOT** DO

- **It does not validate the registry.** `_registry_corrupt_reason` still constrains only *"an
  object of objects"*, and `{"status": []}` is still a valid registry. This branch makes the RENDER
  total; it does not add a record-level schema. That is deliberate — a schema at the loader would
  change what every verb accepts, which is a far larger blast radius than the defect.
- **It does not stop a foreign home forging fleet's words.** Gate §4.3 measured `sup held` and
  `no live workers` renderable as bucket labels and consciously did not file it; `?type` joins that
  set. The forgery always carries a trailing count and always sits after the real fields.
- **It does not close MINOR 1** (`assert_no_terminal_control`'s `limit=200` against a measured
  worst case of 287). Not owed by my brief and not taken. The number is still one nobody measured
  against the real worst case.
- **It does not close MINOR 3** (`_capture_statusline_delegate`'s unbacked `write_text` of a
  machine-wide `shell=True` sink). That is the install half, filed by the lane and by the gate, and
  filed again here.
- **It does not add the MINOR 4 sentence to `BRIEF-TEMPLATE.md`.** See §10 — the template on this
  branch does not contain the digest snippet at all.

---

## 8. THE MUTANTS

*(filled in below from the sweep.)*

---

## 9. THE FLOORS

*(filled in below.)*

---

## 10. WHERE THIS BRIEF WAS WRONG

*(filled in below.)*

---

## 11. REPLICATION

Drivers are in this job's scratch dir (`C:\Users\Techn\.claude\jobs\3e4357c5\tmp`); each builds its
own sandboxed fake home and asserts the real one untouched at both ends.

| what | how |
|---|---|
| four-cell | `drive_fourcell.py` — `git archive 4d78f6c` / `920266c` into two trees plus the working tree's two files; fake `~`, `FLEET_HOME=homeGOOD`, blob sid claimed only by `homeEVIL`, a delegate on both planes |
| type-fuzz | `fuzz_types.py <tree>` — three planes, every field × 18 shapes × 2 base statuses, in process so the failing frame is visible |
| `str()` cost and totality | `probe_str_cost.py <tree>` |
| verb surface | `probe_verbs.py` — gated on `fleet home` printing the temp path, compared normalised |
| re-pin | `repin.py HEAD [--apply]`, then `verify_repin.py HEAD` for the census |
| mutants | `mutants.py` — copy of the working tree, `git init`ed, exec bits restored with `git update-index --chmod=+x`, anchors patched in the target's own newline, line-count neutrality asserted for `bin/fleet.py`, restore checked by sha256 |
| merge cost | `merge_cost.py HEAD main` — base-coordinate hunk intersection plus `git merge-file`, mask `[:-]\d{3,5}` |
| working-tree digest | `digest.py <root>` — the §18 instrument, verbatim |
