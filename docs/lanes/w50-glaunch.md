# w50-glaunch — adversarial gate on `w50/launchfix`

**Subject:** `e662c46` + `4a62e21` over `4d78f6c`. Lane report `docs/lanes/w50-launchfix.md`.
**Gate branch:** `w50/glaunch`, branched at `4a62e21`, identical to `w50/launchfix` at start
(`git diff w50/launchfix w50/glaunch` empty). Nothing fixed here; this branch adds this file only.

## VERDICT: **GATING**

**The Part-1 fix is sound and should land.** I re-ran the reproduction, re-ran both floors,
attacked the census with twenty-one shapes in memory and nine more as real new modules, and — the
result I did not expect — I **retired the branch's single load-bearing unverified belief in its own
favour** (§3). The one-line change is correct, minimal, and its blast radius is smaller than the
brief feared.

**Gating is on three false or incomplete statements the branch ships, not on its code.** This
campaign exists because documents carry stale claims about the current tree. This branch ships
a carve-out census that is wrong by 35 hits at the commit it ships in (F1), leaves a **held entry
document stating the opposite of the truth** about the very change it made (F2), and ships a
census-of-exemptions that mis-names one hole and omits two more, one of which is already live in
the census population (F3). All three are cheap, mechanical repairs. Landing a doc-rot branch
carrying its own doc rot is the recurrence this campaign is supposed to stop.

| # | Severity | Finding | Status |
|---|---|---|---|
| F1 | **MAJOR** | The exempt census the pin ships is **129 hits / 22 files**, not the `94 / 21` it states | MEASURED · **GATING** |
| F2 | **MAJOR** | `CONTRIBUTING.md:41` — a HELD entry doc — now misdescribes the pin this branch changed; one clause is strictly false | MEASURED · **GATING** |
| F3 | **MAJOR** | The carve-out census mis-names one hole (`unannotated` param) and omits two (module-scope path alias, `str.join`); the alias hole is live in the census population | MEASURED · **GATING** |
| F4 | MINOR | Widened `_CHECK_COUNT` false-positives on decimals, issue refs and emphasis joined across a newline | MEASURED |
| F5 | MINOR | On the spaced-path branch, `_tracked_markdown()` splits on spaces | MEASURED |
| F6 | MINOR | The exemption swallows two documents root `CLAUDE.md` treats as current-tree | MEASURED (latent) |
| F7 | MINOR | The template test's hazard assertion omits `install`, so that arm can silently go vacuous | MEASURED |
| F8 | MINOR | *"PREDICTION, written before either run"* is committed **together with** the numbers it predicts, so its precedence is unwitnessed | MEASURED |

Live verbs run against the real home: **none.** No `fleet` verb of any kind was invoked — not
`status`, `peek`, `result` or `doctor`. Everything below is source, tests, git, and shells.
`~/.claude/settings.json` was never written: tripwire sha256
`578bde7b898c6011825e57ba9efb23a75eb29e63e62382b957b45dc09133d918` taken before the first command
and re-checked after both floors — **unchanged**.

---

## Method: how mutants were run without ever touching the working tree

The lane's §4.8 incident (a tool timeout SIGKILLed a mutant loop and left a mutant on
`skills/fleet/SKILL.md`) is a real hazard, and its own lesson — *a `finally`-based restore is the
happy path only* — is right. I used three guards, none of which is `finally`:

1. **Every mutant ran in a throwaway `git clone`** at `C:\Users\Techn\.claude\jobs\d65ea607\tmp\mut`,
   not in the working tree. A SIGKILL mid-loop cannot reach `C:\proga\fleet-w50-glaunch` at all.
2. Restore is `git checkout -- . && git clean -fdq` — from the object store, not from a variable
   the killed process was holding.
3. After **every** mutant, `git status --porcelain` must be empty or the run calls `sys.exit`.
   Both batteries printed `final: CLEAN`.

Pure-predicate probes (§1.1) never wrote a file at all: `census_command_renders(source, name)`
takes source text, so the shapes were fed to it in memory.

**No floor was started with a mutant on disk.** `git status --porcelain | wc -l` = 0 was asserted
as the first clause of the floor command, and re-checked after.

---

## 1. Part 1 — the AST census

### 1.1 The four wave-35 shapes: all caught

Fed directly to `census_command_renders`, no file touched.

```
W35-a  ALIAS (rename py->interp, fleet_py->script_path)   FLAGGED ('interp','script_path')
W35-a2 ALIAS THROUGH TWO HOPS (a -> b -> render)          FLAGGED ('b','c')
W35-b  WHITESPACE VARIANT (tab between the two paths)     FLAGGED ('py','fp')
W35-c  RENDER INSIDE AN APPROVED FUNCTION NAME            FLAGGED ('py','fp')
W35-d  RENDER IN A NESTED (inner) FUNCTION                FLAGGED ('py','fp')
```

**CLEARED.** The rename — the shape that defeated the old pin — does not defeat this one. Confirmed
end-to-end as a real mutant in the clone: unquoting `_render_sup_spawn_task` *and* renaming its
placeholders goes **RED** on `tests/test_rendered_command_quoting.py` (4 failed), while the old
name-scoped scan
`test_no_bare_path_placeholder_is_left_anywhere_in_fleet_py` goes **GREEN — 1 passed**. The lane's
claim about the scoping is exact.

*(One correction to my own first run: that mutant also turns the old file's `[sup_spawn]`
**behavioural** test RED. That is the driver, not the scan. Isolating the scan is what shows the
rename defeats it, and I did.)*

### 1.2 Can a NEW render escape? The honest measurement

Converting an existing censused render to `.format()` goes RED — but only because the pinned count
drops 4 → 3. That is the count pin firing, not the property. The real question is a render that
was never censused, which is exactly how `_install_statusline` arrived. One new module
`bin/zz_new_surface.py`, one unquoted command render each:

| new render shape | census |
|---|---|
| f-string + `Path()`/`sys.executable` — **CONTROL** | **SEEN (RED)** |
| f-string into `subprocess(..., shell=True)`, two paths | **SEEN (RED)** |
| `.format()` | ESCAPED (18 passed) |
| `%`-formatting | ESCAPED |
| concatenation | ESCAPED |
| `str.join` | ESCAPED |
| f-string, paths via **`Path`-annotated parameters** | ESCAPED |
| f-string, **module-scope path alias** (`_ROOT = Path(...)`) | ESCAPED |
| f-string, one path, `settings["x"]["command"] = ...` | ESCAPED |

The control proves the harness sees new modules at all, so the ESCAPED rows are real holes and not
a scan that reaches nothing.

**"Zero false positives" is not vacuous.** Restoring the shipped defect (unquoting
`_install_statusline`) goes **RED, 2 failed / 16 passed**. Adding a *second* broken render **inside
an already-approved function** — where the `(file, function)` identity set does not move — also goes
**RED, 3 failed**. The scan fires on planted violations.

### 1.3 F3 — MAJOR: the census-of-carve-outs is wrong in three places

Wave 45: *any pin shipping a carve-out ships the census of what it exempts.* This one does ship a
census. It is inaccurate:

1. **It names the hole as "a path that arrives as an *unannotated* FUNCTION PARAMETER."** That word
   promises an annotated one is seen. **It is not** — `def r(exe: Path, tgt: Path)` escapes
   (measured above, and in-memory: `INVISIBLE`). The seed test
   `test_a_shell_sink_is_censused_even_with_one_path` repeats the same wording in its docstring.
2. **Module-scope path aliases are not censused at all, and the hole is live.** `_PATH_GLOBALS` is
   a hardcoded two-name allowlist (`INSTALL_ROOT`, `FLEET_HOME`) and `_local_bindings` walks only
   the *enclosing function*, so a module-level `_ROOT = Path(__file__).resolve().parent.parent`
   is neither shape-recognised nor alias-resolved. This is a decision **by name**, in a module
   whose thesis is *"never by the name."* It is not theoretical: measured across the census
   population,

   ```
   bin/fleet.py             FLEET_HOME    L86     (in _PATH_GLOBALS)
   bin/fleet.py             INSTALL_ROOT  L114    (in _PATH_GLOBALS)
   bin/fleet_statusline.py  _INSTALL_ROOT L36     <-- NOT in _PATH_GLOBALS
   ```

   A command render in `bin/fleet_statusline.py` interpolating `_INSTALL_ROOT` is invisible today.
3. **`str.join` escapes and is not in the disclosed family.** The docstring exempts
   "`.format()` / `%` / string-concatenation"; `" ".join([exe, tgt])` is none of those.

Nothing escapes *today* — the shipped renders are all f-strings over recognised shapes. The defect
is the census, and the census is the thing wave 45 says must be right.

### 1.4 CLEARED: the fix itself

- `bin/fleet.py` is **21453 lines**, unchanged. `git diff --stat 4d78f6c 4a62e21 -- bin/fleet.py`
  = `4 +-`: two lines changed one-for-one, **zero inserted**. No `@NNNN` citation can have moved,
  so no self-citation pass is owed. The claim is exact.
- `foreign = bool(incumbent) and "fleet_statusline.py" not in incumbent` — a fleet-owned incumbent
  is not foreign, so re-running `fleet init --statusline` on an already-installed machine
  **does** replace the unquoted command with the quoted one. There is no upgrade dead-end.
  (The operator's live `~/.claude/settings.json` does currently carry the pre-fix unquoted form;
  it is harmless there because that interpreter path has no space. It needs a re-run, not a
  migration.)
- The `--chain` sibling is **not** a second instance of this defect: `_run_delegate` executes the
  operator's own captured incumbent verbatim and interpolates no fleet path.

---

## 2. The reproduction, re-run (brief §5)

Driven through the real `_install_statusline` under `py -3.10`, whose `sys.executable` on this box
is `C:\Program Files\Python310\python.exe`, with `user_settings_path` redirected to a temp file.
Arms B and C must be passed as a **verbatim command line** — `subprocess.run([...])` joins argv
with `list2cmdline`, which backslash-escapes the embedded quotes and mangles subject and control
alike. My first pass made that mistake and it inverted arm C; the numbers below are after fixing it.

```
SUBJECT (pre-fix render)  C:/Program Files/Python310/python.exe C:/.../bin/fleet_statusline.py
CONTROL (= the fix)       "C:/Program Files/Python310/python.exe" "C:/.../bin/fleet_statusline.py"

A  git-bash sh -c        SUBJECT  rc=127   /usr/bin/bash: C:/Program: No such file or directory
A  git-bash sh -c        CONTROL  rc=0     [fleet]: not initialized
B  cmd /c (bare)         SUBJECT  rc=1     'C:/Program' is not recognized ...
B  cmd /c (bare)         CONTROL  rc=1     'C:/Program' is not recognized ...
C  cmd /d /s /c "..."    SUBJECT  rc=1     'C:/Program' is not recognized ...
C  cmd /d /s /c "..."    CONTROL  rc=0     [fleet]: not initialized

post-fix, the string this tree actually writes:  arm A rc=0, arm C rc=0
```

**Every number the lane reported reproduces exactly.** **Correction #3 — CONFIRMED:** under bare
`cmd /c` the control fails too (rc=1 both), so the prior gate's `cmd` receipt was not evidence for
what it claimed. The lane was right to say so, and right that the git-bash arm carries the finding
on its own.

---

## 3. C6 — the branch's one unverified belief, now MEASURED, and it holds

The lane wrote: **"BELIEVED: that Claude Code executes `statusLine.command` via that Node form
specifically; I did not read the CLI's source."** That belief is load-bearing on the highest-blast-
radius line of the branch, so I attacked it — and found a genuine regression *if the belief is
wrong*:

```
                     A git-bash sh -c   B cmd /c (bare)   C cmd /d /s /c "..."
SPACELESS unquoted        rc=0               rc=0               rc=0
SPACELESS QUOTED          rc=0             **rc=1**             rc=0     <-- the fix, under bare cmd /c
SPACED    unquoted        rc=127             rc=1               rc=1
SPACED    QUOTED          rc=0               rc=1               rc=0
```

Under **bare `cmd /c`**, quoting *breaks* a machine whose interpreter path has no space — which is
the operator's own machine. So the belief had to be settled, not assumed.

**Settled two ways, both MEASURED.**

Node's real Windows shell path, driven with stdin closed the way a statusline runner closes it:

```
  COMSPEC via shell:true -> C:\Windows\system32\cmd.exe
  spawn shell:true  SPACELESS unquoted  rc=0   out="[fleet]: not initialized"
  spawn shell:true  SPACELESS QUOTED    rc=0   out="[fleet]: not initialized"
  spawn shell:true  SPACED    unquoted  rc=1   err="'C:/Program' is not recognized ..."
  spawn shell:true  SPACED    QUOTED    rc=0   out="[fleet]: not initialized"
```

And the shipped `claude` binary itself (`C:/Users/Techn/.local/bin/claude`, 287053472 bytes)
contains the shell-spawn helper verbatim:

```
.command].concat(e.args).join(" ");e.args=["/d","/s","/c",`"${o}"`],
e.command=process.env.comspec||"cmd.exe",e.options.windowsVerbatimArguments=!0}
```

That is arm **C**, not bare `cmd /c`. **CLEARED, and stronger than the lane claimed:** the fix is
correct under the runner the binary ships, correct under git-bash, and **regresses nothing on a
spaceless machine**. The only form it breaks under is one the binary does not contain.

*Honest scope:* I matched the shell-spawn helper in the bundle, not a traced call path from
`statusLine.command` into it. That `statusLine` routes through this helper remains BELIEVED — but
on far stronger evidence than "Node usually does this", and the fix is safe under *both* plausible
runners regardless.

---

## 4. The template surface (brief §2)

**Both halves of "already correct, now pinned" are true.** The template has carried
`"{{PYTHON}}" "{{FLEET_INSTALL}}/..." --fleet-home "{{FLEET_HOME}}"` since `dae38bf`, and this
branch does not touch `worker-settings.template.json` (not in `git diff --name-only 4d78f6c
4a62e21`). Mutant: unquoting one hook command's `{{PYTHON}}` goes **RED, 2 failed**.

**The two properties the brief warned are easy to conflate — measured separately:**

| mutant on a hook command | result |
|---|---|
| placeholder quoted, but a **space** injected unquoted after it | **RED (caught)** — spaced coverage is real |
| backslashes **immediately after** the placeholder | RED — incidental, via `after in ('"', '/')` |
| backslashes **after the first forward slash** | GREEN in the new pin… |
| …the same mutant against `tests/test_hooks.py` | **RED** — `TestTemplate::test_all_hook_commands_use_forward_slashes` |

**No conflict with root `CLAUDE.md`'s forward-slash rule**, and the rule is genuinely held — by the
pre-existing `test_hooks.py` pin, not by the new one. The new pin constrains only the single
character following each placeholder; it is spaced-path coverage, not forward-slash coverage. Those
are two properties, both held, by two different tests.

The docstring's pasted bash receipt reproduces exactly:

```
$ bash -c 'echo "C:\Users\Techn\x"; echo C:\Users\Techn\x'
C:\Users\Techn\x
C:UsersTechnx
```

**F7 — MINOR.** In `test_rendering_with_spaced_roots_survives_shlex`, `install`'s space is
load-bearing for `assert install.resolve().as_posix() in argv[1]`, but `install` is **not** in the
`expect` set that carries `assert all(" " in e for e in expect)`. Remove the space from that
fixture path one day and the arm goes vacuous silently. `_spaced_roots`, the sibling fixture for
`bin/fleet.py`, does not have this gap — it asserts the hazard over all five sentinels.

---

## 5. Part 2 — the population derivation

### 5.1 F1 — MAJOR: the shipped census is wrong by 35 at the commit it ships in

`tests/test_doc_claims.py` and `docs/lanes/w50-launchfix.md:348,433` both state
**"94 hits across 21 files at w50."** Re-derived with the pin's own
`find_check_count_claims` + `find_pass_fail_totals` over its own `_HISTORICAL_PREFIXES`:

| tree | tracked md | held | exempt | claims | tallies | **sum** | files |
|---|---|---|---|---|---|---|---|
| `4d78f6c` (pre-branch) | 140 | 27 | 113 | 45 | 48 | **93** | **21** |
| `e662c46` | 141 | 27 | 114 | 78 | 51 | **129** | **22** |
| `4a62e21` (**ships here**) | 141 | 27 | 114 | 78 | 51 | **129** | **22** |

The mechanism is the most predictable one available: **`docs/lanes/w50-launchfix.md` is itself
exempt by construction and carries 36 hits**, so writing the census falsified it. Drop the report
and the tip returns 93 / 21 — the file count the lane states, and one hit short of its number.

**Graded fairly: I could not reproduce `94` under any definition I could construct**, so this is
not a quarrel about counting convention. Every candidate, measured at `4a62e21`:

| counting definition | with the lane's report | without it |
|---|---|---|
| `find_check_count_claims` only | 78 | 45 |
| `find_pass_fail_totals` only | 51 | 48 |
| **both, the natural reading** | **129** | **93** |
| only hits whose number ≠ 28 | 90 | 66 |
| distinct source lines carrying a hit | 109 | 75 |
| files | 22 | **21** |

The file count `21` pins the intended definition to the right-hand column, and the nearest number
there is 93. Whatever produced `94` is not re-derivable from the tree it ships in.

This is a hand-pasted derived number in a document, unheld by any pin, shipped by the branch whose
subject is hand-pasted derived numbers in documents. Under wave 45 the census is not decoration;
it is the thing that makes the carve-out legitimate.

### 5.2 F2 — MAJOR: a HELD entry doc now misdescribes the pin this branch changed

`CONTRIBUTING.md:41`, unmodified by this branch, still reads:

> …`tests/test_doc_claims.py` re-derives the doctor check count, the Python floor and the set of
> shipped verbs from `bin/fleet.py`, and **checks them against `README.md`, `docs/getting-started.md`,
> `docs/concepts.md`, `docs/README.md`, `docs/launch-readiness.md` and this file.** … **each shape
> is held in its canonical phrasing only, so dropping the backticks takes a claim out of its view.**

Both clauses are now wrong, and the branch is what made them wrong:

- The check-count shape is held over **27** files (`CHECK_COUNT_DOCS`), not those six. A reader
  deciding whether their document is in scope gets the wrong answer.
- **"dropping the backticks takes a claim out of its view" is strictly false for shape 2.**
  `strip_markup` removes backticks wholesale, and the branch's own seed test asserts
  `` `23` checks `` → **RED**. The document tells a contributor the exact opposite of what the
  code now does.

`CONTRIBUTING.md` is in `ENTRY_DOCS` *and* in `CHECK_COUNT_DOCS` — the held population, by the
lane's own derivation. Nothing pins prose about the pin, so it is green. And the lane **read this
exact line**: §2.6 quotes its `21`→`23` clause at length and grades it correctly as true history.
It looked at the sentence next door and did not see that its own change had falsified it.

### 5.3 CLEARED: the exclusion mutants, including one the lane did not run

| mutant | population | result |
|---|---|---|
| `**23** checks` in `skills/fleet/SKILL.md` | HELD (never in `ENTRY_DOCS`) | **RED** — the scope fix works |
| `**23** checks` in `docs/NEXT-SESSION.md` | exempt | GREEN |
| `23 checks` in `knowledge/INDEX.md` | exempt | GREEN |
| `checks: 23` in `docs/specs/multi-fleet.md` | exempt | GREEN |
| no mutant (control) | — | GREEN, 87 passed |

The lane's reported scope mutant reproduces. The three exemptions it did not test behave as
designed — a false count in any of them is invisible and always will be.

### 5.4 The 94-hit classification, audited (brief §5)

I read every exempt file that carries a hit. **The classification is right.** The wrong numbers in
`docs/PLAN-PROGRESS.md`, `docs/lanes/**`, `docs/reviews/**`, `knowledge/**` and `supervisor/JOURNAL.md`
are dated ledger rows and quoted arguments; editing them would fabricate, exactly as the ratified
2026-08-05 rule says. `docs/OPERATOR-GATES.md:24` is the clearest case and the lane cites it
correctly — it quotes `29 checks` and `23 checks` inside an argument whose own prose says the truth
is 28. **I found no live current-tree falsehood hiding behind the exemption.**

`CONTRIBUTING.md:41`'s `21`→`23` non-fix is also graded correctly: it is true history, it states
the current number (28) accurately, and the arrow form is disclosed as unheld. Verified — the pin
does not fire on it, and the whole held population is clean (`violations in held population: none`).

**F6 — MINOR, latent.** Two exempt paths are documents root `CLAUDE.md` treats as *current*:
`docs/NEXT-SESSION.md` (*"read … for work past what §18 records"*) and `docs/OPERATOR-GATES.md`
(*"open operator decisions live in"*). Neither carries a live falsehood today — OPERATOR-GATES's
hits are genuine quotations — so this is a gap in the principle, not a defect on the tree. Stated
because it is where the next one lands.

### 5.5 F4 — MINOR: the widened regex has an untested false-positive family

The lane measured false positives against the **open qualifier gap** and pinned nine benign strings.
It did not test markup interacting with numbers. Measured:

```
'### 4.8 Doctor checks, and the views'  -> [8]      <-- a REAL line shape: docs/specs/claim-nonce.md:732
'Python `3.13` checks out'              -> [13]
'See #4217 checks'                      -> [4217]
'**23**\n* checks pass'                 -> [23]     <-- strip_markup joins across the newline
'| 23 | checks |'                       -> []       (tables are safe)
```

Confirmed end-to-end: appending `### 4.8 Doctor checks…` to `docs/SPEC.md`, or
`At startup Python 3.10 checks the interpreter floor.` to `README.md`, each turns
`test_doctor_check_counts_match_the_registered_checks` **RED** on a held file. Both sentences are
things a person writes. The population just went 6 → 27 and `docs/SPEC.md` is section-numbered
throughout. The pin's own docstring warns that *"a pin that fires on unrelated prose gets
suppressed, and then holds nothing"* — this is the family that would do it.

### 5.6 F5 — MINOR: the spaced-path branch splits on spaces

```python
return tuple(sorted(p for p in proc.stdout.split() if p))     # tests/test_doc_claims.py
```

`git ls-files` does not quote spaces. Measured, in the clone:

```
$ git add "docs/My Notes.md"
$ git ls-files '*.md' | grep -i "my notes"   ->  docs/My Notes.md
   _tracked_markdown() derives:  ['Notes.md', 'docs/My']
   4 failed, 69 passed
   FAILED ...test_doctor_check_counts_match_the_registered_checks[docs/My]
   FAILED ...test_doctor_check_counts_match_the_registered_checks[Notes.md]
   (+2 tallies)
```

It fails **loudly**, so it hides no falsehood — but it is simultaneously noisy (four confusing
`FileNotFoundError`s) and blind (the real file's content is never read, so a false count in it goes
unheld). `git ls-files -z` is the shape without this property. Ranked MINOR because no tracked
markdown has a space today; recorded because this is the one branch on which "a path with a space
splits" should not have been reintroduced one file over.

---

## 6. The three corrections to the brief (brief §4) — all three settled

**#1 — "The bold form is not why `docs/SPEC.md` escaped." CONFIRMED, and the brief's diagnosis
would have produced a fix that changed nothing.** Both halves are true and the lane's ranking of
them is right:

```
ENTRY_DOCS at 4d78f6c = README.md, docs/getting-started.md, docs/concepts.md,
                        docs/README.md, CONTRIBUTING.md, docs/launch-readiness.md
                        -- docs/SPEC.md is NOT among them.

old regex vs the shipped line:  '**23** checks' -> []        (bold did defeat it)
                                '23 checks'     -> ['23']    (…but plain would have been in view)
```

Written plainly, `docs/SPEC.md:281` would *still* have been invisible, because nothing ever looked
at the file. **The file-scope miss holds on its own; the markup miss does not.** A fix aimed only
at the bold form would have left the defect in place. Stated plainly, as the brief asked.

**#2 — "§13 was a wrong roster, not just a wrong number." CONFIRMED. The provenance is not
fabricated.** All five recovered checks exist and each cited commit is real:

| check | SPEC.md cites | verified |
|---|---|---|
| `registry` | `875a46c` | `git log -S` — sole hit, ancestor of HEAD |
| `instance_grants` | `9f7fe26` | sole hit, ancestor of HEAD |
| `permission_stalls` | `1b97efb` | sole hit, ancestor of HEAD |
| `identity_witness` | `bd3dfd2` | two hits across all refs; `2878c68` is **not** an ancestor of HEAD, `bd3dfd2` is |
| `supervisor_wedge` | `346a747` | two hits; `aeb0ad6` is **not** an ancestor of HEAD, `346a747` is |

In both ambiguous cases SPEC.md cites the commit that is **actually in this tree's history** rather
than the earliest hit on any ref. That is the better choice, not a lucky one — a naive
`git log -S --reverse --all` would have named the unmerged branch commits. 23 + 5 = 28, and the
count agrees three ways: `grep -c "def _doctor_check_"` → 28, `cmd_doctor`'s `check_calls` → 28,
and the two name sets are identical.

**#3 — "The gate's `cmd` receipt isn't discriminating as stated." CONFIRMED.** See §2: bare
`cmd /c` returns rc=1 for subject *and* control. The correction is right and it matters beyond this
branch.

---

## 7. The incident and the floors (brief §6, §7)

**No mutant residue anywhere.** `git status --porcelain` empty at gate start;
`git diff w50/launchfix w50/glaunch` empty; `skills/fleet/SKILL.md` is **not** in
`git diff --name-only 4d78f6c 4a62e21`. Stronger than an eyeball: the SKILL.md scope mutant is
*proved* detectable — planting `**23** checks` there goes RED — so a survivor would have been
caught by the floor, and the floor is green.

**Floors, on a tree asserted clean as the first clause of the command:**

```
py -3.13 -m pytest -q   ->  4284 passed, 14 skipped, 1 xfailed in 492.38s   rc=0
py -3.10 -m pytest -q   ->  4284 passed, 14 skipped, 1 xfailed in 475.00s   rc=0
py -3.13 --collect-only ->  4299 tests collected
py -3.10 --collect-only ->  4299 tests collected
4284 + 14 + 1 = 4299
```

**Every floor number the lane reports reproduces exactly, on both interpreters.** Collection
re-derived independently on each, and per module: `tests/test_rendered_command_quoting.py` → 18,
`tests/test_doc_claims.py` → 69. Both match. The 3.10 side is the one that matters —
`fleet.MIN_PYTHON_VERSION` is `(3, 10)`.

**F8 — MINOR: the prediction's precedence is NOT verifiable, and I drafted the opposite before
checking.** The brief asked me to verify the prediction preceded the run. It does not, from
history:

```
$ git show e662c46:docs/lanes/w50-launchfix.md | sed -n '450,470p'
  **PREDICTION, written before either run:** 4299 collected on both interpreters ...
  **MEASURED.** ...  4284 passed, 14 skipped, 1 xfailed in 444.07s   rc=0
```

**The prediction and the numbers it predicts land in the same commit**, `e662c46`. `4a62e21` did
not fill in the floors at all — it appended thirteen lines of §6 post-commit numbers (`87 passed`,
`tracked markdown 140 → 141`), which is what its message actually says. So git is silent on the
ordering and *"written before either run"* is an unwitnessed self-report — **BELIEVED, not
MEASURED**, by this repo's own standard that a pasted claim is a claim until something re-runs it.

I am not calling it false. The predicted numbers are unusual ones to guess (4299 collected, and a
skip/xfail split the lane explicitly declines to claim it predicted), all of them reproduce, and
the derivation `18 + 42 + 1 = 61` is independently checkable and checks out. The finding is that
the *evidence* is not what the report implies — a prediction is only evidence if it is committed
before the measurement, and this one was not.

**The tree digest is not the vacuous kind.** The sibling lane's warning is about `git write-tree`,
which hashes the **index** and says nothing about unstaged changes. This lane used a **content
sha256 over files** — *"hashed over all 241 tracked files plus the new untracked test module"* — which
is exactly the digest that does not have that hole, and the arithmetic checks out: `git ls-files`
now returns **242**, i.e. the 241 tracked plus the then-untracked module, now committed.

---

## 8. Graded the other direction

These are worth as much as the findings and they all hold up.

- **The one-line, zero-insertion fix is a real result.** 21453 lines before and after, `4 +-` on
  `bin/fleet.py`, two lines changed one-for-one. No citation moved. Verified, not accepted.
- **The reproduction needed no synthetic fixture and every number in it reproduces**, including the
  awkward one — that the lane's own predecessor's `cmd` receipt was not evidence.
- **The lane corrected its dispatcher three times and all three corrections are right**, including
  the one that makes its own brief-giver wrong.
- **It disclosed a mid-run incident unprompted** and drew the correct lesson from it.
- **It refused two fixes on principle and both refusals are correct** — `CONTRIBUTING.md:41` is
  true history, and the 94 historical hits are past-tree claims whose repair would fabricate. I
  audited the classification file by file and found no current-tree falsehood wearing historical
  clothing.
- **The census is a genuine improvement over what it replaces.** A rename defeats the old scan
  (measured: 1 passed) and does not defeat this one (measured: 4 failed). New modules, new
  functions, and second renders inside approved functions are all caught.
- **The `BELIEVED` it flagged was the right thing to flag**, and it turns out to be true. Flagging
  it is what made it cheap for me to settle.

---

## 9. What this gate did not do

- **No live `fleet` verb was run at all** — not `status`, `peek`, `result` or `doctor`. The findings
  needed none, and the safest read of the fence was to take none.
- I did not trace `statusLine.command` through the `claude` binary to the shell-spawn helper; I
  matched the helper. §3 states that limit where it applies.
- Shapes 1 and 3 of the doc pin (verbs, Python floor) are still `ENTRY_DOCS`-only. The branch says
  so and calls it a known gap rather than a design. I did not attack them; a `fleet frobnicate` in
  `skills/fleet/SKILL.md` is unheld, as documented.
- I did not attack `docs/SPEC.md`'s §13 roster text beyond the five recovered names and the count.

## 10. What would clear the gate

Three mechanical edits, none of them to `bin/fleet.py`:

1. **F1** — re-derive the exempt census at the commit it ships in and state it there
   (129 / 22 at `4a62e21`), or state it as *"93 across 21 excluding this report"* and say why.
2. **F2** — update `CONTRIBUTING.md:41`'s two clauses to the scope and phrasing rule that now ship.
3. **F3** — fix "unannotated" → "any", and add the module-scope path alias and `str.join` to the
   carve-out census. (Fixing the *hole* is optional; fixing the *census of it* is not.)

F4–F7 are MINOR and can ride a later pass.
