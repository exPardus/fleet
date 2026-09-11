# `w50-gd` — adversarial gate on `w50/d`, multi-fleet slice (d) (the statusline)

| | |
|---|---|
| Under gate | `w50/d` @ `99e8164`, base `4d78f6c` |
| This lane | `w50/gd`, worktree `C:/proga/fleet-w50-gd`, branched from `99e8164` |
| Changed by the branch | `bin/fleet_statusline.py` **+214/−2**, `tests/test_statusline_home.py` new (688), `docs/lanes/w50-d.md` new (657) — `git diff --numstat 4d78f6c..99e8164` |
| `bin/fleet.py` | **UNTOUCHED** — `git diff --stat 4d78f6c..99e8164 -- bin/fleet.py` is empty. MEASURED |
| Floors | 4310 collected on py3.13 **and** py3.10; 4295 passed, 14 skipped, 1 xfailed, 0 failed on both. MEASURED |
| Live fleet CLI verbs run | **ZERO.** `fleet home` was run only against a sandbox home I created (the brief's own gate step). No `status`/`peek`/`result`/`doctor` against the live home was needed |
| `~/.claude/settings.json` | sha256 `578bde7b898c6011825e57ba9efb23a75eb29e63e62382b957b45dc09133d918`, `mtime_ns 1786210442854189800` — before and after. MEASURED |
| `~/.claude/fleet-homes.list` | **ABSENT** before and after, checked at five points |
| `fleet init --statusline` | **NEVER RUN.** `bin/fleet_statusline.py` was driven directly with a blob on stdin |

Every line is **MEASURED** (I ran it in this lane and read the bytes) or **BELIEVED**
(reasoning or documentation I did not execute).

---

## 0. VERDICT — **GATING**

The branch is well built and I could not break the thing the brief ranked first. The exit-0
invariant held under 45 hostile input shapes; the new resolution path provably cannot reach the
quarantining loader; the single-home short-circuit is byte-identical to the pre-slice script on
7/7 cases; `bin/fleet.py` really is untouched; and the lane's disclosure of its own two failed
mutant sweeps is the reason I trusted its numbers enough to attack elsewhere.

**It gates on one thing the lane did not look at: what a resolved home that is not the
operator's own is now allowed to put on the operator's screen.** Slice (d) moves two
registry-fed render paths across a trust boundary that did not exist before it, and both are
reachable with nothing but write access to a listed home.

| # | severity | finding | status |
|---|---|---|---|
| **1** | **BLOCKING** | A listed home that claims a session id executes **arbitrary shell commands** in the operator's session, once per refresh, invisibly | MEASURED (§1.1) |
| **2** | **BLOCKING** | A listed home injects **raw ANSI escapes / bare CR / BEL / unbounded length** into the operator's statusline, forging fleet's own row | MEASURED (§1.2) |
| **3** | MAJOR | On a multi-home machine the terminus **collapses three distinct registry-fault words into `[fleet]: no home`**, re-opening P1-13 | MEASURED (§2) |
| **4** | MAJOR | **5 of my 18 mutants survived**, all on the ambiguity count and the painter; the ambiguity count — the whole payload of the lane's §4 defence — is semantically unpinned | MEASURED (§3) |
| **5** | MINOR | `blob_session_id`'s *"NEVER RAISES"* is false (`RecursionError` escapes) — the exact defect `read_registry_at` documents as *"the specific mistake this function exists to avoid"* | MEASURED (§4.4) |
| **6** | MINOR | The capture receipt is not reproducible as written: `capture.log` now holds **16** invocations / 26025 B, not the 13 / 21072 B the report describes | MEASURED (§6) |
| **7** | MINOR | `docs/lanes/w49-dcap.md` §1.1 still types `rate_limits.five_hour.used_percentage` as `int`; the lane corrected it in its own report but not in the document a future lane cites | MEASURED (§6) |
| **8** | MINOR | The probe session inherited `FLEET_WORKER` from the launching environment — env hygiene was partial; it was the settings file that contained it | MEASURED (§8) |

**Findings 1 and 2 are the same shape and I believe one decision closes both:** the lane's own
§5 chain-file plane error, fixed with its option **(i)**, removes finding 1 entirely, and
finding 2 needs one sanitising function on the roster render. Neither fires today —
`~/.claude/fleet-homes.list` does not exist — so this is a decision to take **before** the list
does, which is exactly what this slice exists to make possible.

**Both are pre-existing defects that this branch makes reachable across a trust boundary**, not
defects this branch authors. That distinction is §7, and it is the operator's to act on.

### The other direction — CLEARED, and each of these is a real result

- **`bin/fleet.py` untouched.** MEASURED, empty diff. No self-citation pass owed; the
  `w50/launchfix` lane cannot collide.
- **exit 0 on every path.** 45 hostile shapes, rc=0 and empty stderr on every one (§1).
- **No quarantine, by construction.** Whole-program AST call graph, with a positive control (§4.1).
- **The audit re-run non-vacuously.** 4-home population including the live home *and* a corrupt
  home; 0 mutating events; 686-file live census unchanged; positive control fires (§4.2).
- **Single-home byte-identity.** 7/7 under one identical `INSTALL_ROOT` (§4.3).
- **The refusal clause is honoured.** No rendered string carries a remedy or a chosen home;
  `NO_HOME_LINE` is used as a constant, never retyped (§4.5, §4.7).
- **No re-spelling of §5's order.** `resolve_home()` is called; the adapter drops nothing the
  predicate reads (§4.6).
- **Both of the lane's corrections to the dispatcher are RIGHT** (§5), and one is campaign-level.

---

## 1. THE TWO GATING FINDINGS

Both have the same root: `main()` assigns `fleet.FLEET_HOME = decision["home"]` and everything
downstream — the delegate chain file *and* the roster — is then read out of a home the operator
may not control. Pre-slice, both came from `$FLEET_HOME`.

Claiming a session id is **unauthenticated**. A registry is plain JSON; any home may list any
sid under `workers[*].session_id`. Session ids are not secret — they are transcript filenames.

The ambiguity arm is a **partial mitigation and only for member sessions**: if the operator's
own home *also* claims the sid, `resolve_home` raises, `resolve_blob_home` returns
`HOME_AMBIGUOUS` with `home=None`, and no home is applied. I measured that first and it blocked
my first attempt. It does not help the majority case — **every ordinary interactive session is
claimed by no home at all**, because only `fleet spawn`ed workers are ever written to a
registry. A single claim by one hostile home is then a clean `hit`.

### 1.1 Cross-home arbitrary shell execution — BLOCKING, MEASURED

`_run_delegate` runs the chain-file command with `shell=True`. `main()` assigns the resolved
home **before** `_delegate_rows`:

```
# bin/fleet_statusline.py @ 99e8164
line 555: decision = resolve_blob_home(payload)
line 556: if decision["home"] is not None:
line 557:     fleet.FLEET_HOME = decision["home"]
line 569: for row in _delegate_rows(payload):      <- subprocess.run(command, shell=True)
ordering: assignment at 557 precedes the delegate at 569: True
```

Driven end to end. `$FLEET_HOME` is the operator's own `homeGOOD`; `homeEVIL` is merely listed
in `~/.claude/fleet-homes.list` and claims the session id; the operator's own home does not
(an ordinary interactive session):

```
OLD (pre-slice)
   rc=0  stdout='[operator-statusline]\r\n[fleet]  idle 1 7h'
   >>> homeEVIL's shell command executed: False

NEW (w50/d)
   rc=0  stdout='[operator-statusline]\r\n[fleet]  idle 1 7h'
   >>> homeEVIL's shell command executed: True   marker='arbitrary code ran'
```

**The rendered line is unchanged.** The operator sees nothing. `refreshInterval` is 10, so the
command runs every ten seconds for the life of the session.

### 1.2 Cross-home terminal-escape injection — BLOCKING, MEASURED

Two render paths take registry text verbatim:

- `_bucket(w)` returns `worker["status"]` unmodified, and `_LABEL.get(bucket, bucket)` falls
  back to that raw string (`_bucket_order`'s own docstring says *"unknown statuses last"*, so
  they render rather than being dropped);
- `_reset_clock(iso)`'s docstring says *"Any other shape -> the raw value"*, and it returns
  `str(iso)`.

Same fixture as §1.1; only `homeEVIL`'s registry changes:

```
=== OLD ===  ($FLEET_HOME = homeGOOD, sid claimed only by homeEVIL)
  ansi-clear-line    rc=0 len=  20 ESC=0 bare-CR=0 BEL=0  clean
  ansi-cursor-up     rc=0 len=  20 ESC=0 bare-CR=0 BEL=0  clean
  cr-overwrite       rc=0 len=  20 ESC=0 bare-CR=0 BEL=0  clean
  bell+long          rc=0 len=  20 ESC=0 bare-CR=0 BEL=0  clean
  osc-title          rc=0 len=  20 ESC=0 bare-CR=0 BEL=0  clean
  limit_reset_at     rc=0 ESC=0  repr: '[fleet]  idle 1 7h'

=== NEW ===
  ansi-clear-line    rc=0 len=  44 ESC=2 ...  '[fleet]  \x1b[2K\x1b[1;31mFLEET COMPROMISED 1 7h'
  ansi-cursor-up     rc=0 len=  24 ESC=2 ...  '[fleet]  \x1b[1A\x1b[2K 1 7h'
  cr-overwrite       rc=0 len=  39 bare-CR=1  '[fleet]  idle\r[fleet]  all clear 1 7h'
  bell+long          rc=0 len= 417 BEL=1      '[fleet]  \x07XXXX...(400)'
  osc-title          rc=0 len=  26 ESC=1 BEL=1 '[fleet]  \x1b]0;pwned\x07 1 7h'
  limit_reset_at     rc=0 ESC=1  '[fleet]  lim 1 7h resets \x1b[5mRESET-INJECTED'
```

`\x1b[1A\x1b[2K` erases the line **above** the statusline — Claude Code's own output.
`cr-overwrite` renders on a terminal as `[fleet]  all clear`: a **forged fleet status**, in
fleet's own nameplate, on the surface the operator trusts to tell them the fleet's state.

**The ASCII pin cannot see this.** ESC is `0x1b`:

```
repr('\x1b[2K') -> isascii(): True
```

so `test_the_rendered_line_is_pure_ascii` passes on every one of these.

---

## 2. THE TERMINUS EATS THREE DIAGNOSES — MAJOR, MEASURED

`render_statusline` distinguishes three registry faults, and the comment three lines above the
code records **P1-13**, the finding that fixed exactly this collapse: *"the rename makes absence
ambiguous, so `not initialized` was what a just-quarantined fleet printed too — byte-identical
to a box that never ran `fleet init`, on the one surface the operator reads continuously."*

`resolve_home` steps 3/4 gate on `home_is_initialized()` = `read_registry_at()[0]`, which is
`False` for all three, so all three fall to §5 step 5 and `render_home_terminus` prints before
`render_statusline` is ever called:

```
fault in $FLEET_HOME   population    OLD (pre-slice)                NEW (w50/d)                collapsed?
absent                 single-home   [fleet]: not initialized       [fleet]: not initialized   no
corrupt                single-home   [fleet]: registry unreadable   [fleet]: registry unreadable no
quarantined            single-home   [fleet]: registry quarantined  [fleet]: registry quarantined no
wrongshape             single-home   [fleet]: registry unreadable   [fleet]: registry unreadable no
absent                 MULTI-HOME    [fleet]: not initialized       [fleet]: no home           ** YES **
corrupt                MULTI-HOME    [fleet]: registry unreadable   [fleet]: no home           ** YES **
quarantined            MULTI-HOME    [fleet]: registry quarantined  [fleet]: no home           ** YES **
wrongshape             MULTI-HOME    [fleet]: registry unreadable   [fleet]: no home           ** YES **

read_registry_at() on each fault:
  absent       ok=False reason='not_initialized' home_is_initialized=False
  corrupt      ok=False reason='unreadable'      home_is_initialized=False
  quarantined  ok=False reason='quarantined'     home_is_initialized=False
  wrongshape   ok=False reason='unreadable'      home_is_initialized=False
```

An operator whose registry is **corrupt** is told they have **no home** — a configuration
problem, not a corruption problem, and the wrong remedy. The lane's §2.1 CASE 4b compared a
*bare* home (`not initialized` → `no home`) and reasonably read that as a wording change; the
corrupt and quarantined arms were not driven, and those are the ones that lose a diagnosis.

`resolve_home` is behaving to spec here — this is slice (d) wiring that spec onto a surface that
already had a better answer.

---

## 3. THE MUTANTS — 18 PLANTED, 12 KILLED, **5 SURVIVED**, 1 WITHDRAWN

Driver contract, following the lane's own two disclosed failures rather than repeating them:
patches **raw bytes** in the file's own newline; asserts `occurrences == 1` **before running
anything** and aborts otherwise; runs a **clean baseline first** and refuses to plant into a red
one; **no `-x`**, so the failure count is evidence; restores from the original bytes and proves
it by sha256 after every mutant, in a `finally`.

Target suite: `test_statusline_home.py` + `test_views_doctrine.py` + `test_terminal_surface.py`
+ `test_install_home_split.py` + `test_quarantine_is_not_a_fresh_install.py` +
`test_steering.py` — every file that references `fleet_statusline`, a superset of the lane's.

```
CLEAN BASELINE: 386 passed, 2 skipped

KILLED         G1   terminus and ambiguity verdicts SWAPPED in the renderer            3 failed
**SURVIVED**   G2   ambiguity count guard dropped -- a hand-built record renders (None) 386 passed
**SURVIVED**   G3   ambiguity count LIES: always reports 2                             386 passed
KILLED         G4   renderer loses its tolerance for a hand-built record               1 failed
KILLED         G5   the DEGRADE constant becomes HOME_DEFAULT, not HOME_SINGLE         3 failed
**SURVIVED**   G6   _paint_terminus paints the WHOLE line, breaking plain()'s round-trip 386 passed
**SURVIVED**   G7   _paint_terminus ignores `color` and never paints                   386 passed
KILLED         G8   HOME_NONE renders nothing -- falls through to the roster           4 failed
KILLED         G9   blob_session_id drops .strip()                                     1 failed
KILLED         G10  resolution moved AFTER the delegates -- the split-brain render     4 failed
KILLED         G11  the ambiguity branch degrades instead of reporting the ambiguity   2 failed
KILLED         G12  population_is_multi_home ignores the list-readability term         1 failed
 withdrawn     G13  the resolved home applied even when None -- EQUIVALENT MUTANT      386 passed
KILLED         G14  NO_HOME_LINE retyped as a literal instead of used as a constant    1 failed
KILLED         G15  the ambiguity COUNT is off by one AT ITS SOURCE                    1 failed
**SURVIVED**   G16  the ambiguity COUNT reports the whole population, not the claimants 386 passed
KILLED         G17  HOME_AMBIGUOUS renders the terminus word instead of its own        1 failed
KILLED         G18  the ambiguity word gains a paste-ready `--fleet-home <path>`       2 failed

FINAL RESTORE sha256 4d2cfe747c005a3b5ae1d55810b37d3d9f1a0c698af59c7b7c37fcf5f9069863  == base: True
```

**The survivors cluster exactly where the brief predicted — `render_home_terminus` and
`_paint_terminus`, what the author added last.**

**G3 is the one that matters.** The lane's §4 defends the refusal clause on the ground that *"the
honest one-line residue of 'facts, and no chosen home' is the COUNT"*. A mutant that hard-codes
`count = 2` — so a session claimed by five homes reports two — passes all 386 tests. G16 confirms
it from the source side: reporting `len(pop["homes"])` instead of `len(look["hits"])` also
survives, because in every fixture the population size happens to equal the claimant count. G15
(`+1`) dies, so what exists is a **constant-matching pin, not a semantic one**: the count is
checked against the literal `2` in a fixture where two of two listed homes claim the sid.

The count is the entire informational payload of the only new word this slice renders. It should
be pinned against a population where claimants ≠ members, and at ≥3.

**G2** leaves the renderer emitting `[fleet]: home ambiguous (None)` for a hand-built record —
on the arm the lane's own *"TOLERANT OF A HAND-BUILT RECORD"* docstring is about, and which
`test_the_renderer_tolerates_a_hand_built_record` (G4, killed) covers only for the terminus.
**G6 and G7** show the painter is entirely unpinned in both directions: it can paint nothing, or
paint everything and break the `plain(line)` round-trip its docstring exists to preserve.

**G13 is withdrawn as an equivalent mutant, not counted as a gap.** `decision["home"] or
fleet.FLEET_HOME` is a self-assignment whenever `home` is `None`, which is every state except
`HOME_LOOKUP`. Stating it because the honest tally is 5 survivors of 18 run, not 6.

**G12's first anchor matched 0 times and the driver aborted it, planted nothing and ran
nothing** — my indentation was wrong. Re-run with the corrected anchor, it dies. Recording this
because it is the same trap the lane hit, and the abort is the only reason it was visible.

---

## 4. THE OBLIGATIONS, ONE AT A TIME

### 4.1 exit 0 on every path — CLEARED, and by construction as well as by drive

45 shapes, each driven as a **process** against a three-home sandbox. `rc == 0` and
`stderr == b""` on every one:

empty stdin · stdin closed (`DEVNULL`) · whitespace only · malformed JSON · truncated JSON ·
`[]` `"a string"` `123` `null` `true` `["<uuid>"]` · `session_id` = `null` `123` `12.5` `{}`
`{"a":1}` `[]` `["x"]` `true` `""` `"   "` `false` · key absent · sid nested only · sid matching
nothing · sid hitting one home · sid hitting a *different* home · sid hitting two (ambiguity) ·
sid 100 000 chars · sid with NUL + traversal · sid with a newline · a **5 MB** blob with the sid
at the end · non-UTF-8 bytes (`\xff\xfe`) · valid JSON in UTF-16 · a lone surrogate escape ·
**JSON nested 200 000 deep** · a NUL byte mid-JSON · `$FLEET_HOME` registry corrupt × 3 · the
homes list as binary garbage / 200 000 junk lines / empty / **a directory**.

```
QUARANTINE / WRITE CENSUS
  homeA:       added=[] removed=[] changed=[]
  homeB:       added=[] removed=[] changed=[]
  homeCorrupt: added=[] removed=[] changed=[]
  LIVE C:/proga/claude-fleet/state fleet.json.corrupt.* : before=[] after=[]
ALL CASES rc==0 AND stderr empty: True
```

**The corrupt-registry case, proved by construction.** Whole-program AST call graph over
`bin/fleet.py` + `bin/fleet_statusline.py` (504 function defs), rooted at each new symbol:

```
ROOT sl.resolve_blob_home        (26 functions reachable)  -- no load_registry, no _quarantine_registry
ROOT sl.blob_session_id          (1)   NO FORBIDDEN SINK REACHABLE
ROOT sl.population_is_multi_home (2)   NO FORBIDDEN SINK REACHABLE
ROOT sl.render_home_terminus     (2)   NO FORBIDDEN SINK REACHABLE
ROOT sl._paint_terminus          (1)   NO FORBIDDEN SINK REACHABLE
ROOT sl.main                     (62)  only `run` <- sl._run_delegate (the delegate, by design)

POSITIVE CONTROL -- same walker, from a root that DOES call load_registry:
   *** load_registry        <- ['fleet.__CONTROL__']
   *** _quarantine_registry <- ['fleet.load_registry']
   *** rename               <- ['fleet._quarantine_registry']
   CONTROL OK

_quarantine_registry's caller set, by AST:  fleet.load_registry     (sole caller — CLAUDE.md re-derived)
```

The two sinks the walker flagged under `resolve_blob_home` are false positives of a deliberately
over-broad sink list: `open` is `open(path, "r", …)` inside `read_registry_at`, and `replace` is
`str.replace` inside `home_identity`. Both read.

### 4.2 The audit, re-run with a positive control and without wave 48's vacuity

Wave 48's audit was clean because the population was empty. Mine used a **4-home population that
includes the live home and a home whose registry is corrupt**, so the resolution genuinely reads
both:

```
population read for the audit: ["C:/proga/claude-fleet", ".../homeA", ".../homeB", ".../homeCorrupt"]
live registry readable=True workers=155 sids=155
live census: 686 files under C:\proga\claude-fleet\state

PHASE 2 (SUBJECT): 0 mutating/spawning audit events
LIVE census: added=[] changed=[] removed=[]
LIVE quarantine artifacts: []       SANDBOX quarantine artifacts: []

PHASE 3 (POSITIVE CONTROL): 5 events -- the hook MUST see these
   +++ ('os.mkdir', ...)  ('open(WRITE)', ..., "'w'")  ('os.rename', ...)
   +++ ('os.remove', ...)  ('subprocess.Popen', ...)
CONTROL SEES write+rename+mkdir+spawn: True
VERDICT: subject events = 0, control events = 5. Audit is NON-VACUOUS.
```

Independent corroboration: the live home's `state/events.jsonl` (2558 events) contains **zero
`registry_corrupt` events, ever**, and no `fleet.json.corrupt.*` artifact exists.

### 4.3 `single-home short-circuit` — CLEARED, and the justification is right

Driven OLD vs NEW under **one identical `INSTALL_ROOT`** (a scratch install dir holding a copy of
`bin/fleet.py`, with only the statusline file swapped), so the legacy population term and every
path are the same in both arms:

```
SINGLE-HOME (no list at all)                       MULTI-HOME (3-entry fixture list)
  no sid                        IDENTICAL=True       no sid                  IDENTICAL=True
  sid -> homeA                  IDENTICAL=True       sid -> homeA            IDENTICAL=True
  sid -> homeB                  IDENTICAL=True       sid -> homeB            IDENTICAL=False
  sid -> nobody                 IDENTICAL=True       sid -> nobody           IDENTICAL=True
  sid -> BOTH (ambiguous)       IDENTICAL=True       sid -> BOTH             IDENTICAL=False
  no sid, $FLEET_HOME corrupt   IDENTICAL=True       ...corrupt              IDENTICAL=False
  sid -> homeB, corrupt         IDENTICAL=True       ...                     IDENTICAL=False
  >>> ALL CASES BYTE-IDENTICAL: True
```

**The reason the lane gives is the right one and the code says so.** `population_is_multi_home`'s
docstring is headed *"NOT A PERFORMANCE FEATURE"* and cites §5's arming paragraph. I grepped the
whole new region for a performance justification and found none — the only speed numbers appear
as the argument that the short-circuit is *not* about speed. **No finding.**

### 4.4 `resolver pure-function` — CLEARED, with one false docstring claim

`resolve_blob_home` calls `fleet.resolve_home()`. §5's order is not re-implemented: the branches
read `res["step"]` rather than re-deriving it, and the ambiguity arm re-calls
`fleet.lookup_home_for_sid` rather than re-deriving step 2 by hand. I looked specifically for a
partial re-spelling — an inlined step, an ordering assumption, a hand-made step 2 — and found
none.

The one adapter is `population_is_multi_home`, which reshapes a `resolution_population` record
into the `lookup_home_for_sid` shape `_multi_fleet_population_is_live` expects. **It drops
nothing the predicate reads**: the predicate reads exactly `list_ok`, `population` and `legacy`.
It does *not* read `list_invalid_lines`, which `resolution_population` carries with the comment
*"CARRIED FOR THE ARMING RULE"* — so the adapter is faithful and the pin
(`test_the_short_circuit_agrees_with_fleets_own_predicate`) is real. Mutant G12 confirms the
`list_ok` term is load-bearing and pinned.

**Finding 5 (MINOR).** `blob_session_id`'s docstring: *"A PURE FUNCTION, AND IT NEVER RAISES …
Four degenerate inputs are real and all four answer `""`."* There is a fifth, and it does not
answer `""`:

```
blob_session_id except clause, by AST:  except (TypeError, ValueError, UnicodeDecodeError)
   [RAISE] deep nesting (200k)       -> RecursionError: maximum recursion depth exceeded ...
   [RAISE] deep nesting, dict (200k) -> RecursionError: ...
   [ok  ] bytes / bytearray / non-UTF8 / None / int / list  -> ''
```

`MemoryError` reaches it by the same route. **Not reachable in production** —
`resolve_blob_home` wraps the call in `except BaseException`, driven:
`resolve_blob_home(deep) -> {'state': 'single_home', 'sid': '', 'hits': 0}`. It is MINOR for
that reason, and worth recording only because `fleet.read_registry_at` — which this same lane
cites by name — catches `RecursionError, MemoryError` explicitly and its comment says *"THE TWO
ON THE END ARE THE POINT … copying the sibling's three-tuple here is the specific mistake this
function exists to avoid."* The new function is a three-tuple, one file over, in the same wave.

### 4.5 The refusal clause — CLEARED, and the lane's third position is sound

Every string literal added by the diff, and every rendered one:

```
rendered f-strings, entire diff:   f"{_NAME}{head}{_RESET}{sep}{tail}"
                                   f"{PREFIX}: home ambiguous ({count})"
paste-ready command scan over rendered strings: (no rendered string contains a remedy/command)
```

No `--fleet-home`, no `FLEET_HOME`, no home path, no `fleet homes`, no `fleet init`. Mutant G18,
which appends a paste-ready `--fleet-home <path>`, **dies on 2 tests** — so the negative is
pinned, not merely true.

**Grading the argument, since the lane was told to defend a position and took a third.** The
clause's binding half is the *"never"*, and the shipped line satisfies it. The *"facts + the
`fleet homes` view"* half is what a **refusal** must print, and §5 step 5 puts views on the other
side of that split in its own words. The lane did not drop the clause silently — it argued it in
§4 and pinned the negative. **Sound.**

One flaw in the reasoning, not the code: the lane lists *"no 'run `fleet homes`'"* among the
things the clause forbids. The clause **requires** the `fleet homes` view in refusals; it forbids
a *paste-ready command with a chosen home*, which `fleet homes` is not. So the lane could have
printed it without violating the clause and declined on width grounds instead. The outcome is
the same and I file no finding — but the stated reason is not the clause's.

### 4.6 `NO_HOME_LINE` as a constant — CLEARED

```
454:        return _paint_terminus(fleet.NO_HOME_LINE, color)
grep '\[fleet\]: no home' bin/fleet_statusline.py
432:    named remedy, and views render `[fleet]: no home` and exit 0"* -- ...   (a docstring quoting §5)
```

The literal appears exactly once, inside a docstring quoting the spec. Mutant G14, which retypes
it, dies.

### 4.7 One observation, no finding

`resolve_blob_home` returns `hits: 0` on a `lookup` verdict — the key is only populated on the
ambiguity branch. Harmless today (only `render_home_terminus` reads it, only for
`HOME_AMBIGUOUS`), but a record whose `hits` is `0` on a hit is a trap for the next consumer.

---

## 5. THE METHOD FINDINGS — BOTH RIGHT, ONE IS CAMPAIGN-LEVEL

### 5.1 `git write-tree` cannot serve the tree-identity rule — **CONFIRMED, and it is yours to fix**

Reproduced directly. With `bin/fleet_statusline.py` modified in the working tree and nothing
staged:

```
HEAD tree      : 01763f4b02962d9ff44ad1accb3dd7a8464df04f
git write-tree : 01763f4b02962d9ff44ad1accb3dd7a8464df04f     <- with 'M bin/fleet_statusline.py' UNSTAGED
status         :  M bin/fleet_statusline.py
HEAD's blob    : 8f1a34c518d7b8c4ee679ee6e23e9c4a26116ae5
worktree blob  : 37001bab4b41b7467b7493c4eda72e7a3df2b262
=> write-tree == HEAD tree while the working tree DIFFERS: YES
```

`git write-tree` hashes the **index**. As a guard against *staged* drift it works; as the
instruction's actual intent — *"prove the tree sha is identical before and after each run"*, i.e.
prove a test run did not modify the working tree — **it cannot fail while the index is
untouched**, which is every lane's normal state. **This is a campaign-level finding, not a lane
one:** every lane that inherited that instruction inherited a vacuous check. The lane's
replacement (a sha256 digest over every tracked path's bytes) is the right instrument and I used
it for my own floors (§6.2).

Worth adding: this repo already ships a stronger instrument than either. `tests/conftest.py`'s
session-scoped `_the_real_install_plane_is_byte_identical_afterwards` hashes the git-tracked code
plane before and after the whole run. It caught **my own** contamination when I let a mutant
sweep overlap a floor run (§6.2) — a real positive control for it, obtained by accident.

### 5.2 *"Two claude versions in play"* is malformed — **CONFIRMED**

```
claude --version -> 2.1.226 (Claude Code)
grep -rn '2\.1\.222' bin/  -> 0 hits
```

Every occurrence is prose or a historical record: `state/pin-pass.json`'s stamp of the last
version at which the native pin tier passed, plus `tests/pin_usage_contract.py`,
`tests/test_pin_usage_contract.py`, `tests/integration/test_native_pin.py`,
`docs/lanes/w48-pin.md`, `docs/lanes/w49-dcap.md`. **One CLI is installed. 2.1.222 is a stamp,
not a runtime.** The lane is right and the brief should stop carrying the claim.

---

## 6. THE CAPTURE RE-DRIVE — GRADED, AND THE RECEIPT HAS DRIFTED

Re-analysed from the lane's `capture.log` myself, as a file.

**It now holds 16 invocations / 26025 B, not the 13 / 21072 B the report describes** (finding 6,
MINOR). The three extra arrived at exactly 10.00 s spacing after the lane's snapshot — the
`refreshInterval` timer kept firing, which is the lane's own §8 observation continuing past the
moment it wrote the number. Nothing is wrong with the measurement; the *receipt* is not
reproducible as written, and a gate re-running `analyse.py` gets 16.

**Were they distinct refreshes, or one blob read N times? DISTINCT — decisively:**

```
distinct PIDs             : 16 of 16     <- a re-read of one blob would share a pid
distinct t_ns             : 16 of 16
distinct blob BYTES       : 16 of 16
monotonic t_ns            : True
inter-arrival gaps (s)    : [3.71, 0.37, 0.43, 5.44, 2.26, 2.27, 1.21, 4.25,
                             10.01, 10.0, 10.0, 10.01, 10.0, 10.0, 10.01]
distinct session_id values: {'d3ebc580-85b8-4b62-8633-40991363c8ce'}
session_id types          : {'str'}
sid == env var on every one: True (16/16)
```

Sixteen separate processes, monotonic, all bytes distinct. The load-bearing claim is
**stronger** than the report's, not weaker.

**Schema, re-derived:**

```
first render top-level keys : 13, session_name PRESENT
later render top-level keys : 15
IN FIRST BUT NOT LATER      : []
IN LATER BUT NOT FIRST      : ['prompt_id', 'rate_limits']
rate_limits.five_hour.used_percentage   types=['float']            sample=7.000000000000001
context_window.used_percentage          types=['NoneType', 'int']  sample=22
cost.total_cost_usd                     types=['float', 'int']     sample=0.16805900000000001
```

**Grading "non-load-bearing".** Upheld, and now measured rather than asserted:

```
does slice (d) read any of them?
  session_name / rate_limits / used_percentage / context_window / prompt_id /
  version / transcript_path   -> referenced in bin/fleet_statusline.py: False
  session_id                  -> True
```

Slice (d) reads **only** `session_id`. The divergences cannot bite it. But the claim is
*"non-load-bearing for slice (d)"*, not *"non-load-bearing"* — `isinstance(7.000000000000001,
int)` is `False`, and a third divergence the lane did not report (`cost.total_cost_usd` is
`float` **and** `int` across the 16) is the same class. **Finding 7 (MINOR):**
`docs/lanes/w49-dcap.md` §1.1 still types that field `int`. The lane recorded the correction in
its own report but not in the document a future consumer would cite, so the wrong type is still
the one on the shelf.

---

## 7. THE CHAIN FILE — DIAGNOSIS RIGHT, ONE OPTION WORKS, AND IT IS **PRE-EXISTING**

Driven in process with `fleet.user_settings_path` monkeypatched to a temp file. **`fleet init
--statusline` was never run**; the real `~/.claude/settings.json` sha256 and `mtime_ns` are
unchanged (header).

**Is the diagnosis right? YES — MEASURED.**

```
install A (home A): chained: pwsh -c my-own-statusline.ps1
                    chain file homeA\state\statusline-chain.json -> ['pwsh -c my-own-statusline.ps1']
install B (home B): (no "chained:" line)
                    chain file homeB\state\statusline-chain.json -> []
  install A captured the operator's statusline: True
  install B captured the operator's statusline: False
```

`foreign = bool(incumbent) and "fleet_statusline.py" not in incumbent` is `False` on install B,
so `_capture_statusline_delegate` is never called — **and the settings entry is overwritten
anyway, with no refusal and no warning**, because the refusal arm lives inside `if foreign:`.
The operator's delegate then exists only in home A's chain file. The lane's diagnosis is exactly
right; I would add only that the silence is part of the defect.

**Do the two filed options solve it? ONE DOES.**

```
(i)  MACHINE PLANE  -- after BOTH installs the chain holds: ['pwsh -c my-own-statusline.ps1']
     operator's delegate survives install B: True    <- SOLVES IT
(ii) INSTALL PLANE  -- after BOTH installs install B's chain holds: []
     operator's delegate survives install B: False   <- DOES NOT SOLVE the re-capture half
```

Option (ii) fixes the per-session and per-environment variation but **not** the re-capture
failure that the finding is about. The lane's table concedes this as *"wrong if two installs ever
alternate in that entry"* — which is precisely the scenario. **The lane's preference for (i) is
correct, and (ii) should not be presented as an equivalent alternative.**

**Regression, or pre-existing? PRE-EXISTING — MEASURED both ways.**

The base revision already scopes the chain file to the home:

```
BASE bin/fleet.py            : return state_dir() / "statusline-chain.json"
BASE bin/fleet_statusline.py : return Path(fleet.state_dir()) / "statusline-chain.json"
```

and the base script already loses the delegate when `$FLEET_HOME` moves — driven in §4.3, where
OLD prints `DELEGATE-C` under `FLEET_HOME=homeCorrupt` and `DELEGATE-A` under `homeA`.

**What slice (d) changes is the blast radius, and that is the part that matters:** the delegate
moves from *per environment variable* (an operator act, deliberate, machine-wide) to *per
session, automatically, within one unchanged environment*. Measured — same `$FLEET_HOME=homeA`
in both rows:

```
sid -> homeB   OLD rc=0 'DELEGATE-A\r\n[fleet]  idle 3 6h'
               NEW rc=0 'DELEGATE-B\r\n[fleet]  work 2 6h  idle 1 6h  +1 dead'
```

**So: it does not block the landing as a regression.** It blocks it as **finding 1**, which is a
different claim about the same code — the pre-existing plane error is what lets a *foreign*
home's shell command run, and slice (d) is what makes a foreign home reachable. Fixing the plane
with option (i) closes finding 1 as a side effect, because a machine-scoped chain file is not
attacker-controlled by a listed home.

---

## 8. SAFETY, AND **WHY** I AND THE LANE WERE CONTAINED

**Why, not whether.** The seam is `Path.home()`: `homes_list_path()` is
`Path.home() / ".claude" / "fleet-homes.list"` with **no env override**, but `Path.home()` honours
`USERPROFILE` on Windows. So the entire multi-home surface is drivable from outside the suite
against a fixture list in a temp fake home. I verified this independently before measuring
anything, and gated every run on it:

```
GATE 3 ok: CLAUDE_CODE_SESSION_ID absent from child env
GATE 1  `fleet home` rc=0
  got  = 'C:/Users/Techn/.claude/jobs/e541283a/tmp/gd/homeA'
  want = 'C:/Users/Techn/.claude/jobs/e541283a/tmp/gd/homeA'
  MATCH (as_posix normalised) = True
GATE 2  homes_list_path -> ...\gd\fakehome\.claude\fleet-homes.list ; 3 fixture members read
REAL homes list exists BEFORE: False    AFTER: False
```

**And it is non-vacuous, which is the part wave 48 lacked.** My audit ran against a **4-home**
population containing the live home and a corrupt home (§4.2); my OLD/NEW comparison differs
between the single-home and multi-home arms only because the fixture list was actually read
(§4.3). Had `USERPROFILE` not taken effect, every multi-home row would have collapsed into the
single-home row and the whole sweep would have been the wave-48 result again.

**The lane's containment, checked rather than accepted:**

- `~/.claude/settings.json` sha256 `578bde7b…` / `mtime_ns 1786210442854189800` — **identical to
  the value the lane recorded, and to `w49-dcap`'s**. Nothing drifted between lanes.
- `~/.claude/fleet-homes.list` **absent**, confirmed at five points across my own runs.
- Live `state/events.jsonl`: the only `w50-d` events are the manager's own `spawned` /
  `turn_started` / `status_changed`. No `cleaned`/`killed`/`archived`/`steered`/`respawned`.
  The lane's *"zero fleet CLI verbs"* is consistent with the event record. The worker sid it
  reports (`bd8542c8-ce6e-43cd-a29f-a5b357555913`) matches the registry.
- **Probe session stopped.** `capture.log` is static across a 3-second re-stat, and no process
  on the machine carries `w50d` in its command line.
- Zero `registry_corrupt` events in 2558 live events, ever. No `fleet.json.corrupt.*` artifact.

**Finding 8 (MINOR), and it is exactly the "clean for the wrong reason" shape.** Every captured
header reads:

```
env.FLEET_WORKER='sup|inc-20260808T173831Z-c6d4|boot'
```

The probe inherited a **fleet worker identity** from the launching environment. The lane's §7.5
says `CLAUDE_CODE_SESSION_ID` was stripped, which reads as env hygiene; `FLEET_WORKER` was not.
It cost nothing — the probe declared its own `.claude/settings.json` with two commands and no
fleet hooks, so nothing ever read the variable — but **the containment was the settings file,
not the environment**, and the report attributes part of it to the environment.

**My own containment**, stated the same way: every drive ran as a child process with
`FLEET_HOME` set to a sandbox home, `USERPROFILE`/`HOME` redirected to a temp fake home, and
`CLAUDE_CODE_SESSION_ID` removed; the one in-process suite (`chainfix.py`) monkeypatched
`fleet.user_settings_path` before touching anything and re-hashed the real file afterwards. All
scratch lives under `C:/Users/Techn/.claude/jobs/e541283a/tmp/` and is safe to delete.

**One contamination of my own, disclosed.** I let the mutant sweep start while the py3.10 floor
was still running, so that floor's `bin/fleet_statusline.py` was mutated under it. The suite's
own session-scoped guard caught it:

```
AssertionError: the test suite modified git-tracked install-plane files: ['bin\\fleet_statusline.py'].
```

The run's counts were right (4295/14/1) but its rc was 1, so I discarded it and re-ran the floor
on a clean tree (§9). Recording it because it is the same class of error the brief warns about —
*never start a floor run with a mutant on disk* — approached from the other direction.

---

## 9. FLOORS

Collected counts re-derived with `--collect-only` on both interpreters, never by arithmetic:

```
py -3.13 -m pytest --collect-only -q  ->  4310 tests collected
py -3.10 -m pytest --collect-only -q  ->  4310 tests collected
```

```
PREDICTION, STATED BEFORE THE RUN: 4310 collected -> 4295 passed, 14 skipped, 1 xfailed, 0 failed

py -3.13  rc=0  4295 passed, 14 skipped, 1 xfailed in 493.26s

py -3.10 (re-run on a CLEAN tree after the contamination in §8):
  status --porcelain BEFORE: ''
  working-tree digest BEFORE: a8eb3e41e693d812ea01afc117d075b4f651b7ef9c9013954b0e4332dea2073c  files=242
  MEASURED (py -3.10): rc=0  4295 passed, 14 skipped, 1 xfailed in 425.02s
  working-tree digest AFTER : a8eb3e41e693d812ea01afc117d075b4f651b7ef9c9013954b0e4332dea2073c  files=242   IDENTICAL=True
```

`4295 + 14 + 1 = 4310`. Both interpreters, both matching the lane's numbers exactly.

One more incidental receipt for §5.1, from that same run: `git write-tree` reported
`01763f4b…` before **and** after, unchanged — across a run that also left a new untracked file
(`docs/lanes/w50-gd.md`) in the tree. It cannot see untracked files either.

**On "verify the prediction preceded the run": I cannot, and I will not claim otherwise.** The
report and the code landed in one commit; there is no independent timestamp for the prediction.
What I *can* say is that the numbers are right, that I predicted the same numbers in writing
before my own runs and met them, and that the lane's §7.1 table records a *baseline* of 4238 →
4223 that is consistent with 72 new tests (4238 + 72 = 4310) — an arithmetic check the lane
would have had to fake deliberately rather than by adjusting after the fact.

---

## 10. WHAT I DID NOT MEASURE

- **A real multi-home machine.** Every multi-home drive used a fixture list under a redirected
  `Path.home()`. Appending to `~/.claude/fleet-homes.list` is RATIFIED DESTRUCTIVE and I did not.
- **Findings 1 and 2 against the live home.** Both were driven in the sandbox only. I did not
  put any sid, chain file or registry row into `C:/proga/claude-fleet`.
- **`claude attach` after slice (d) lands.** Inherited from `w49-dcap2` §4, not re-driven.
- **The interactive and `-p` session classes.** The capture log is all `--bg`.
- **Whether the lane's prediction preceded its run** (§9).
- **py3.10 mutant sweep.** Mutants were run on py3.13 only; the floors cover 3.10.
- **`_run_delegate`'s timeout behaviour** under a hostile delegate from a foreign home — finding
  1 already establishes execution, so the timeout is a mitigation question, not an existence one.

---

## 11. REPLICATION

All instruments are this lane's, under `C:/Users/Techn/.claude/jobs/e541283a/tmp/`:

```sh
py -3.13 setup2.py  <tmp>/gd     # sandbox: 3 homes, distinguishable rosters, per-home chains
py -3.13 gate.py                 # the seam gates -- run this before believing anything below
py -3.13 hostile.py              # §4.1  45 hostile shapes + quarantine census
py -3.13 reach.py                # §4.1  AST call graph + positive control
py -3.13 audit.py                # §4.2  live-home audit, 4-home population, positive control
py -3.13 oldnew.py               # §4.3  OLD vs NEW under one INSTALL_ROOT
py -3.13 collapse.py             # §2    the three-word collapse
py -3.13 mutants.py              # §3    G1-G14
py -3.13 mutants2.py             # §3    G12 (fixed anchor), G15-G18
py -3.13 neverraises.py          # §4.4  the NEVER RAISES claim
py -3.13 chainfix.py             # §7    _install_statusline, redirected settings path
py -3.13 recapture.py            # §6    re-analysis of the lane's capture.log
py -3.13 xhome.py                # §1.1  cross-home shell execution
py -3.13 inject.py               # §1.2  cross-home terminal-escape injection
py -3.13 floor.py -3.13          # §9    floor + working-tree digest
py -3.13 floor.py -3.10
```

`git write-tree` receipt (§5.1) is three shell lines and is quoted in full there.
