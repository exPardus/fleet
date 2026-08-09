# w51-dtype — the statusline render made total over field TYPES

**Subject:** `w51/dtype`, branched from `w50/gd2` @ `920266c` (which contains `w50/d` @ `5a47819`
plus that gate's verdict — `git merge-base --is-ancestor w50/d w50/gd2` returns 0, MEASURED).
**Discharges:** gate `w50-gd2`'s single MAJOR, its mutant X4, its X7 equivalence question, and the
third self-citation re-pin pass.
**Fence held:** commits on `w51/dtype` only. No push, no merge, no other ref moved.

Every line below is tagged **MEASURED** (a command was run and its output is pasted or counted) or
**BELIEVED** (reasoning I did not drive).

---

## SUMMARY — WHAT LANDED

| | |
|---|---|
| the MAJOR — a foreign home erases fleet's row | **CLOSED**, four-cell, three revisions, actual bytes |
| the displacement direction | **NOT re-opened** — op delegate 1, evil delegate 0, every cell |
| siblings, systematically hunted | **1390 fuzz combinations, 59 raising → 0**; plane A had one sink, plane B had five |
| the verb surface | **no sibling**, driven on three revisions |
| mutant X4 | **REAL**, closed, re-planted **RED** |
| mutant X7 | **EQUIVALENT — I agree with the gate**, and §4.2 shows what keeps that true |
| the third re-pin pass | **31 moved, 43 content-verified, 0 defects**, 170 pins green |
| floors, `py -3.13` **and** `py -3.10` | **4489 / 4474 / 14 / 1 / 0 — prediction met exactly, four full runs across two trees** |
| working-tree digest | **identical at all four points**, `files=244` |
| `~/.claude/fleet-statusline-chain.json` | **ABSENT** after two full floors |
| one mutant survivor of my own (R9) | found, disclosed, **closed**, prediction revised BEFORE any floor ran |

**Owed and NOT done, stated once here so it is not discovered as an omission:** a FOURTH re-pin pass
after the merge with `main` (§6), and gate `w50-gd2`'s MINOR 1 and MINOR 3, neither assigned to this
lane (§7).

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
| `bin/fleet.py status` | 5 (3 in the gated probe + 2 in a follow-up that printed the table) | the temp sandbox home |
| `bin/fleet.py status --all` | 3 | the temp sandbox home |
| `bin/fleet.py doctor` | 3 | the temp sandbox home |
| `bin/fleet_statusline.py` (as a subprocess) | 16 (three iterations of the four-cell driver: 3×2 + 2×2 + 2×3) | the temp sandbox home, or the temp foreign home the sandboxed homes-list named |
| `fleet init`, `fleet init --statusline`, `fleet homes --add`, `fleet doctor --repair` | **0** | — |

The in-process drivers (`fuzz_types.py`, `probe_str_cost.py`) are not CLI invocations; they set
`FLEET_HOME` and `USERPROFILE`/`HOME` to temp directories **before importing `fleet`**, which is
when `FLEET_HOME` is read. The mutant sweep runs `pytest`, whose own `conftest.py` sandboxes
`user_settings_path` by name — and §9 re-asserts the real plane after two full floors rather than
trusting that.

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

## 4. THE TWO SURVIVING MUTANTS THE GATE LEFT ME

### 4.1 X4 — **REAL, and now closed**

Gate `w50-gd2` MINOR 2 is exactly right. `assert_no_terminal_control` is the only pin that would
catch a non-palette SGR, and the only shipped test that reached `+N unknown` rendered with
`color=False` — so `paint()` returned the text unpainted and the escape never existed. **A pin that
cannot reach the rendering path it claims to cover is a coverage claim that is false**, which is
this campaign's most-repeated lesson.

Closed by `TestTheOverflowCounterIsRenderedInColour`, and closed with its own non-vacuity guard:
`test_the_colour_case_really_differs_from_the_plain_one` asserts `painted != flat` **and**
`plain(painted) == flat`, because a `color=True` case that silently rendered plain would pass the
new test and re-open the very gap it exists to close. Re-planted on the fixed tree: **RED, 1
failed.**

### 4.2 X7 — **I AGREE WITH THE GATE, and the agreement is not free**

The gate's argument, verbatim: *"the cap is still 3, the overflow count is still right, the order is
still deterministic, and no documented property distinguishes the first three unknown buckets from
the last three."* **I agree.** X7 survives the target suite on my tree too (816 passed), and I file
no finding.

**But it would have stopped being true at my own commit if I had not looked.** My fix introduces
`?type` — a bucket name **fleet** authors — into the unknown region, and `?` (0x3F) sorts before
every letter. That is precisely the documented property the gate correctly said did not exist at
`5a47819`. Measured four ways over one bucket set:

```
buckets: ['?type', 'alpha', 'beta', 'gamma', 'idle']

SHIPPED (exemption, first 3)     (['idle', '?type', 'alpha', 'beta', 'gamma'], hidden=0)
SHIPPED + X7 (exemption, last 3) (['idle', '?type', 'alpha', 'beta', 'gamma'], hidden=0)
  -> fault word visible in both: True True          <- EQUIVALENT

NO EXEMPTION + first 3           (['idle', '?type', 'alpha', 'beta'], hidden=1)
NO EXEMPTION + X7, last 3        (['idle', 'alpha', 'beta', 'gamma'], hidden=1)
  -> fault word visible:         True False         <- NOT equivalent
```

So the verdict is neither *"the gate was right"* nor *"the gate was wrong"*: **the gate was right,
and the thing that makes it right is now load-bearing.** The cap exemption (§3.3) is what holds it,
`test_the_cap_can_hide_only_names_the_attacker_chose` is the pin that stops the next lane removing
it by accident, and mutant R6 is the receipt that the pin fires.

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

### 6.1 `main` moved a FOURTH time before I finished — re-measured, same verdict

At `16:19:48` — while this report was being written — `main` went `7b2ff75` → **`5cb0e4e`** (three
commits, two of them merges of other wave-51 lanes). **I did not move it**; `git reflog show main`
attributes every entry to another session, and this lane's only writes are five commits on
`w51/dtype`. The claim above would have rotted silently, which is precisely why it names the sha.
Re-driven against `5cb0e4e`:

```
base 4d78f6c   mine 64b784d   main 5cb0e4e
bin/fleet.py: mine 17 hunks x main 28 hunks -> 15 overlapping ranges, 19 base lines
  of those, carrying a `:NNNN` citation: 19
  NON-citation overlapping lines ......: 0
  git merge-file predicts 12 conflict block(s); CITATION-ONLY: 12; other: 0
```

`main` touched `bin/fleet.py` by two lines in that interval; the verdict is unchanged (28 hunks
instead of 27, same 12 citation-only conflicts, still zero functional overlap). **The number that
matters is not the conflict count but its stability**: two independent `main` positions, four days
of other lanes' work between them, and the merge is still mechanical. What is NOT stable is the
re-pin — every one of those `main` moves shifts `bin/fleet.py`'s line numbers again, which is the
whole reason the fourth pass is owed to whoever performs the merge rather than to this branch.

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
- **It does not ship the type-fuzz as a test.** `fuzz_types.py` is the instrument gate `w50-gd2`
  §10 asked for and it found five sinks the shipped pins did not, but it is a driver in a scratch
  dir, not a pin. Turning it into a parametrized test file is the obvious next move and is a
  deliberate non-goal here: it would have moved the floor prediction after the prediction was
  committed, and the six pins it motivated (R9) already cover the specific shapes it found. Filed,
  not taken.

---

## 8. THE MUTANT SWEEP — 11 PLANTED, 10 KILLED, 1 EQUIVALENT

### 8.1 The preconditions fired, which is how I know they are load-bearing

My first sweep **refused to plant anything** — MEASURED:

```
CLEAN BASELINE  rc=1  2 failed, 808 passed, 2 skipped, 1 xfailed in 93.36s
REFUSING TO PLANT: the baseline is RED, so every 'kill' below would be the
baseline's failure wearing a mutant's name.
```

The two failures were `TestCollaboratorInstall::test_{interpreter_shim,posix_cli_shim}_is_tracked_
and_executable`: `shutil.copy2` cannot carry a git exec bit on Windows, so `bin/fleet` and
`bin/hooks/run_py.sh` came back `100644` in the extracted copy. Repaired with
`git update-index --chmod=+x` rather than by excluding the two tests. **Eleven kills reported
against that baseline would have included two the baseline already owned.**

Four more assertions, each with a named failure behind it in this campaign's record:

| assertion | the failure it prevents |
|---|---|
| anchors patched in the TARGET'S OWN newline | `core.autocrlf=true` hands out CRLF; `\n`-spelled anchors match zero times and nine skips read as nine kills (`w50/d` §6a; gate `w50-gd2` §7 hit it again) |
| anchor occurs EXACTLY ONCE, patch asserted applied | a no-op patch scores a survivor |
| `bin/fleet.py` mutants LINE-COUNT NEUTRAL | one blank line above `registry_path_at` scores 4 kills with zero behaviour change (`w50-gd2` §7.2 measured it) |
| restore in `finally`, checked by sha256 | a floor run started with a mutant on disk |

**Target suite, disclosed rather than implied** — nine files (`test_statusline_home`,
`test_terminal_surface`, `test_quarantine_is_not_a_fresh_install`, `test_status_render_tolerance`,
`test_view_quarantine`, `test_views_doctrine`, `test_self_citations`,
`test_retired_sid_citations`, `test_doc_claims`). Clean baseline **816 passed, 2 skipped, 1
xfailed** (810/2/1 before the six R9 pins landed). This is not the whole floor, and no verdict below
is a claim about the whole floor.

### 8.2 The results

| | mutant | verdict | suite |
|---|---|---|---|
| R1 | the status narrowing is removed from `status_snapshot` | **RED** | 7 failed |
| R2 | `registry_status` coerces with `str()` instead of refusing | **RED** | 5 failed |
| R3 | `_safe` stringifies a non-string again | **RED** | 2 failed |
| R4 | `_bucket` reads the raw status again | **RED** | 21 failed |
| R5 | the stale filter is `is not None` again | **RED** | 5 failed |
| R6 | the `TYPE_FAULT` bucket loses its cap exemption | **RED** | 4 failed |
| R7 | the supervisor `state` narrowing is removed | **RED** | 4 failed |
| R8 | the supervisor age narrowing is removed | **RED** | 6 failed |
| R9 | the non-dict worker-row guard is removed | **SURVIVED**, then **RED** | 810 passed → 1 failed |
| X4 | the `+N unknown` counter is painted a NON-palette red | **RED** | 1 failed |
| X7 | `_bucket_order` keeps the LAST 3 unknowns, not the first | **SURVIVED — equivalent** | 816 passed |

```
RESTORED bin/fleet_statusline.py      sha256=931eb5f3ba1b1696 (== base: True)
RESTORED bin/fleet.py                 sha256=73c9f615ab001a44 (== base: True)
```

**R1–R8 are the receipt that the new pins are not vacuous.** Each reverts one half of this branch's
own fix and each goes RED. R2 is the `str()`-coercion the brief warned against, and it is caught by
name by `test_the_two_absences_stay_distinguishable_from_a_type_fault`.

### 8.3 R9 — the finding of my own I did not see coming, in MY new code

The non-dict worker-row guard I added had **no pin behind it**, so deleting it changed nothing any
test could observe. That is a false coverage claim on code written the same afternoon, which is
this campaign's most-repeated defect landing on the lane trying to discharge it. Six tests close it
and the re-plant is RED (`1 failed, 815 passed`).

One honest note about the log rather than a quiet omission: R9 is the one mutant reported
`line-count neutral=False`. It lives in `bin/fleet_statusline.py`, which carries no self-citations,
so the neutrality guard correctly does not gate it — the `False` is the instrument reporting a fact,
not a suppressed refusal.

---

## 9. THE FLOORS — PREDICTION MET EXACTLY, ON BOTH INTERPRETERS

```
=== interpreters ===
Python 3.13.12
Python 3.10.1

=== collect ===
py -3.13 --collect-only:  4489 tests collected in 5.46s
py -3.10 --collect-only:  4489 tests collected in 11.03s

=== FLOOR py -3.13 ===
working-tree digest BEFORE : d5c63ab896d299403d44c72f70a5a476b0275dd6c9f88a610a8711e4bb7bc4ca  files=244
4474 passed, 14 skipped, 1 xfailed in 473.20s (0:07:53)
working-tree digest AFTER  : d5c63ab896d299403d44c72f70a5a476b0275dd6c9f88a610a8711e4bb7bc4ca  files=244

=== FLOOR py -3.10 ===
working-tree digest BEFORE : d5c63ab896d299403d44c72f70a5a476b0275dd6c9f88a610a8711e4bb7bc4ca  files=244
4474 passed, 14 skipped, 1 xfailed in 413.46s (0:06:53)
working-tree digest AFTER  : d5c63ab896d299403d44c72f70a5a476b0275dd6c9f88a610a8711e4bb7bc4ca  files=244
```

| | predicted | 3.13 | 3.10 |
|---|---|---|---|
| collected | 4489 | **4489** | **4489** |
| passed | 4474 | **4474** | **4474** |
| skipped | 14 | **14** | **14** |
| xfailed | 1 | **1** | **1** |
| failed | 0 | **0** | **0** |

`4474 + 14 + 1 = 4489` on both. **3.10 is not optional and it was not spot-checked at the collection
layer** — the floor is `fleet.MIN_PYTHON_VERSION`, `py -3.13` is only this machine's preference, and
gate `w50-gd2` §10 recorded that it had run 3.10 at `--collect-only` only. Both are full runs here.

**The digest is byte-identical at all four points, `files=` included.** Not `git write-tree`, which
hashes the INDEX and therefore cannot fail with unstaged changes — every wave-50 brief shipped that
dead check. And the digest is **CHECKOUT-RELATIVE** (gate `w50-gd2` MINOR 4): `d5c63ab8…` is not a
tree identity and is not reproducible from `34bc1b9` in another worktree. Only the before/after
PAIR means anything, and all four are inside one checkout.

**The real machine plane, after two full floors — MEASURED:**

```
~/.claude/fleet-homes.list            exists: False
~/.claude/fleet-statusline-chain.json exists: False
~/.claude/settings.json  mtime  2026-08-08 22:34:02.854189800 +0500
```

`~/.claude/fleet-statusline-chain.json` — the file this branch's lineage introduces — is **ABSENT**,
as it was for `w50/d` and for the gate. The `settings.json` mtime predates this session.

### 9.1 Re-floored with the report in the tree — SAME NUMBERS, and the regress named

The run above was made on the tree at `34bc1b9`, i.e. **before** the report existed. Re-run in full
on both interpreters at `a93532a`, with the report committed:

```
py -3.13 --collect-only:  4489 tests collected
py -3.10 --collect-only:  4489 tests collected

=== FLOOR py -3.13 ===
working-tree digest BEFORE : 46df3684e666be3420f45b8a0f0ea9085d211107007fce78e20512ec39ce4cbf  files=244
4474 passed, 14 skipped, 1 xfailed in 475.45s (0:07:55)
working-tree digest AFTER  : 46df3684e666be3420f45b8a0f0ea9085d211107007fce78e20512ec39ce4cbf  files=244

=== FLOOR py -3.10 ===
working-tree digest BEFORE : 46df3684e666be3420f45b8a0f0ea9085d211107007fce78e20512ec39ce4cbf  files=244
4474 passed, 14 skipped, 1 xfailed in 431.95s (0:07:11)
working-tree digest AFTER  : 46df3684e666be3420f45b8a0f0ea9085d211107007fce78e20512ec39ce4cbf  files=244

~/.claude/fleet-homes.list            exists: False
~/.claude/fleet-statusline-chain.json exists: False
~/.claude/settings.json  mtime  2026-08-08 22:34:02.854189800 +0500
```

Four floors, two trees, two interpreters, the same **4489 / 4474 / 14 / 1 / 0** every time. Note the
digest legitimately differs between the two trees (`d5c63ab8…` vs `46df3684…`) and is identical
within each — which is exactly what the instrument claims and all it claims.

**The regress, named rather than hidden.** This paragraph is itself an edit made after the run it
describes, and the commit carrying it also corrects the `fleet status` count in §1 from 6 to 5 and
the statusline-subprocess count from 12 to 16 — I had miscounted my own census, which is the kind of
thing this campaign asks lanes to say out loud. **That final commit is documentation-only**: it
touches `docs/lanes/w51-dtype.md` and nothing else, it adds no collected test, and the tree it
describes differs from the four-times-floored tree by exactly this section and those two numbers.
Chasing that to a fixpoint would take a fifth floor to describe a sixth tree; stating the delta is
the honest end of the regress.

---

## 10. WHERE THIS BRIEF WAS WRONG

**"Use the working-tree digest in `docs/lanes/BRIEF-TEMPLATE.md`" — THE TEMPLATE ON THIS BRANCH DOES
NOT CONTAIN IT.** MEASURED: `docs/lanes/BRIEF-TEMPLATE.md` at `920266c` is **99 lines** and contains
the string `digest` **zero** times. The amendment landed on `main` as `c6ddf0f` (+63 lines) **after
`w50/gd2` was cut**, so a lane fenced to this branch cannot follow that instruction as written. I
used `docs/lanes/w50-d.md` §18, which is the text the template copied and which IS on this branch.
An instruction naming a file that does not hold the thing, on the branch the lane is fenced to, is
this campaign's inherited-enumeration defect in its smallest form. *(And gate `w50-gd2` MINOR 4's
one missing sentence — that the digest is checkout-relative — is still missing from the template on
`main` at `7b2ff75`. I carry it in §9 and in the tool's own docstring.)*

**"`str(["idle"])` … is a bracket-bearing attacker-chosen string arriving *after* the point where
brackets get neutralised" — MEASURABLY FALSE.** `_safe` stringified FIRST and neutralised SECOND, so
`_safe(["idle"])` was `"('idle')"` — the brackets were always neutralised. **The conclusion is right
and the reason is not.** §3.2 gives three reasons that survive a probe: the P1-13 byte-collapse
(load-bearing), 149 ms per refresh, and the loss of the wrong-shape/nothing-recorded distinction.
Shipping the brief's verdict with my own evidence is worth more than repeating a mechanism that
falls over in five lines.

**"Coercing everything to `str()` makes the render total" — TRUE, and I doubted it before I measured
it.** I expected a nesting depth that parses but cannot be stringified from inside the render's call
stack, which would have made `str()` non-total as well as wrong. There is none: `json.loads` accepts
2000-deep arrays and `str()` survives all of them. `str()`-coercion really would have been total. It
is rejected for being **wrong**, not for being incomplete, and I say so rather than banking an
argument I could not support.

**"Likeliest: that the type-totality fix is small" — SPLIT, and the split is the useful part.** The
narrowing that closes the gate's exact finding IS small: one helper, one call site, three lines of
logic. What is not small is what the fuzz found behind it — `render_statusline` had **five** type
sinks, not one, four of them `KeyError`s on an ABSENT key, a shape the gate never drove, on the
plane every shipped hostile-status test already uses. The brief's instinct was right and its reason
was inverted: small at the boundary the gate named, five times larger one file over.

**"That `str()`-coercion plus the existing `_safe()` is enough (I think it is not, and I have said
why)" — RIGHT, for a better reason than the one given.** See above.

**"That X7 is genuinely equivalent" — RIGHT, and it stays right only because of a change I made
deliberately.** §4.2 has the four-way measurement. Left alone, my own fix would have converted the
gate's correct judgement into an incorrect one at my commit.

**"That the third re-pin pass is the last one" — WRONG, and knowably so.** A **fourth** is owed after
the merge: `main` has moved twice more since the gate measured (`4d74d22` → `c6ddf0f` → `7b2ff75`)
and both sides re-pin the same citation sites. Priced read-only in §6 — 12 conflict blocks, all
citation-only, 0 non-citation overlapping lines. My fence forbids the merge, so this branch cannot
make that pass and does not claim to.

**A citation slip, named because a gate reader will go looking.** The brief says *"`w50-gd2` §21 says
the post-merge tree needs a third difflib re-pin pass"*. `w50-gd2` has sections 0–12; **§21 is
`w50-d`'s** (*"MERGE PREP — `main` MOVED UNDER THIS BRANCH"*), and the gate endorses it in its own
§8. Both documents say the same thing; only the pointer is wrong.

**What the brief could not have known — two, and both are about instruments, not code.**

1. **The one mutant survivor of my own was in the fix's own new code.** R9 deletes a guard I added
   this branch and nothing noticed. A lane that plants mutants only on the code it was *sent* to fix
   never finds that class.
2. **My merge-cost classifier reproduced the wave-45 blind spot inside the tool built to avoid
   it.** Masking `:\d{3,5}` leaves a range END standing, because the END carries no colon — so it
   reported a purely-citation conflict as functional. Caught only because the driver PRINTS what it
   classifies instead of counting it. The brief warned about that shape *in the re-pin driver*; it
   did not occur to me that it would reappear in a different tool I wrote the same afternoon.

**One thing the brief got right that is worth confirming rather than assuming.** Its four-cell table
has two columns. I drove **three** revisions, because two columns cannot show what gate `w50-gd2`
§2.2 shows: that the same hostile record is HARMLESS at `4d78f6c` and erasing at `920266c` — that
the defect belongs to this slice. Two columns prove the fix works; three prove whose defect it is.

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
