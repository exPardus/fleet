# w50 — the launch blocker on quickstart step 4, and two pins scoped to their author's examples

**Lane:** build. Branch `w50/launchfix`, base `4d78f6c`. Both gate-2 MAJORs from
`docs/lanes/w49-gc2.md`.

Every line below is tagged **MEASURED** (I ran it in this lane and the output is quoted or
reproducible from the command given) or **BELIEVED** (inherited, reasoned, or not re-run here).
Where the brief and my measurement disagree, the measurement wins and the disagreement is
recorded in **WHERE THIS BRIEF WAS WRONG** at the end.

---

## 0. Safety — every `fleet` command run, and which home it touched

**MEASURED.** Three `fleet` invocations, all against a home created fresh for this lane at
`C:/Users/Techn/.claude/jobs/5bd99e65/tmp/w50/throwaway-home`:

| command | home it acted on |
|---|---|
| `fleet home` | throwaway (the gate) |
| `fleet init` | throwaway |
| `fleet doctor` | throwaway (read-only) |

The home was being CREATED, so `--fleet-home` could not be used. `FLEET_HOME` was set and
**`CLAUDE_CODE_SESSION_ID` was removed from the child environment** (`env -u
CLAUDE_CODE_SESSION_ID FLEET_HOME=… py -3.13 "$REPO/bin/fleet.py" …`) — that removal, not the env
var, is what makes the fence hold, because with a session id present resolution step 2's
sid→home lookup can answer with the LIVE home and win over the env var.

The whole run was gated on `fleet home` invoked exactly as every later command was, compared
NORMALISED:

```
gate: want = C:/Users/Techn/.claude/jobs/5bd99e65/tmp/w50/throwaway-home
gate: got  = C:/Users/Techn/.claude/jobs/5bd99e65/tmp/w50/throwaway-home
GATE PASSED
```

`INSTALL_ROOT` was this throwaway worktree throughout (`bin/fleet.py` resolves it from
`__file__`). **`~/.claude/settings.json` was never written** — Part 1's repro drives
`_install_statusline` in-process with `fleet.user_settings_path` monkeypatched to a temp file, and
the suite's `conftest.py` already redirects `Path.home()`. `~/.claude/fleet-homes.list` was never
touched. `fleet init` was never run against the live home.

A `git worktree add --detach` at `4d78f6c` was created under the job tmp dir to measure the base
collection count, and removed afterwards. **No ref was moved.**

---

## PART 1 — `_install_statusline` rendered an unquoted command

### 1.1 The defect, reproduced rather than inherited

**MEASURED.** `py -3.10` on this machine *is* `C:\Program Files\Python310\python.exe`, so the
hazard needed no synthetic fixture: running the repro under 3.10 makes `sys.executable` carry a
real space. `_install_statusline` was driven for real, with `user_settings_path` redirected to a
temp file, and the string it wrote was executed through three shell forms:

```
SUBJECT (as `fleet init --statusline` wrote it at 4d78f6c):
    C:/Program Files/Python310/python.exe C:/proga/fleet-w50-launchfix/bin/fleet_statusline.py
CONTROL (both paths quoted):
    "C:/Program Files/Python310/python.exe" "C:/proga/fleet-w50-launchfix/bin/fleet_statusline.py"

A  git-bash sh -c        SUBJECT  rc=127
      stderr: /usr/bin/bash: C:/Program: No such file or directory
A  git-bash sh -c        CONTROL  rc=0
      stdout: [fleet]: not initialized
B  cmd /c (bare)         SUBJECT  rc=1
      stderr: 'C:/Program' is not recognized as an internal or external command
B  cmd /c (bare)         CONTROL  rc=1
      stderr: 'C:/Program' is not recognized as an internal or external command
C  cmd /d /s /c "..."    SUBJECT  rc=1
      stderr: 'C:/Program' is not recognized as an internal or external command
C  cmd /d /s /c "..."    CONTROL  rc=0
      stdout: [fleet]: not initialized
```

After the fix, the same script prints **rc=0 for the SUBJECT in arm A and arm C**.

**A CORRECTION TO THE GATE'S RECEIPT.** The gate reported *"rc 127 under git-bash, rc 1 under cmd,
with a quoted control at rc 0."* The rc numbers are all real and I reproduced every one. But **arm
B is not evidence**: `cmd /c <string>` without `/s` strips the first and last quote character of
the whole line, so it mangles the CONTROL too and returns rc 1 for both. The control only reaches
rc 0 under the `cmd /d /s /c "<command>"` wrapping — which is what Node's `shell: true` emits on
Windows and therefore the realistic runner. **BELIEVED:** that Claude Code executes
`statusLine.command` via that Node form specifically; I did not read the CLI's source. The
git-bash arm is discriminating on its own and does not depend on that belief.

### 1.2 README quickstart step 4 — confirmed

**MEASURED.** `README.md:117-119`:

```
# 4. Optional: the always-on statusline (a plugin can't ship one)
#    This writes ~\.claude\settings.json, your machine-wide Claude Code config.
fleet init --statusline
```

The brief's step number is **correct**. One qualification it did not carry: the step is labelled
**"Optional"**. It is still the fourth numbered thing in the quickstart and the failure is on every
statusline refresh forever, so I did not downgrade it. **MEASURED:** `README.md:121` already read
`all 28 checks` and was correct.

### 1.3 The discriminating pair, reproduced before anything changed

**MEASURED**, via a planter that asserts `occurrences == 1` before running anything, prints the
sha256 before and after, and restores byte-identically. Base `bin/fleet.py` sha256
`b76dc65d6007ba71e6c59dd47f6ac0502f92588466a22dfd1d1b5a2e4b50ef2c`.

| mutant | `test_no_bare_path_placeholder_is_left_anywhere_in_fleet_py` |
|---|---|
| unquote `_steer_supervisor_release`, names kept `{py}`/`{fleet_py}` | **rc=1, 1 failed** (RED) |
| the same unquoting, renamed `{interp}`/`{script_path}` | **rc=0, 1 passed** (GREEN) |

Both restored, `RESTORED=YES`. The gate's claim is confirmed exactly: **a pin a rename defeats is
pinning a name.**

**The planter's guard earned its keep on its first run.** `bin/fleet.py` is CRLF on disk; my
anchors were written with `\n`, the count came back 0, and the planter aborted with rc 3 instead of
running the suite against an unmutated file and reporting a green that meant nothing.

### 1.4 The fix

**MEASURED.** One line, `bin/fleet.py:6133-6134`, no lines inserted:

```python
-        # Forward slashes: this command string is executed through a shell.
-        "command": f"{Path(sys.executable).resolve().as_posix()} {script}",
+        # A shell runs this: forward slashes, and QUOTED -- a spaced path splits.
+        "command": f'"{Path(sys.executable).resolve().as_posix()}" "{script}"',
```

`git show 4d78f6c:bin/fleet.py | wc -l` → **21453**; `wc -l < bin/fleet.py` → **21453**.
**No self-citation pass is owed**, because no `fleet.py:NNNN` reference can have moved.

### 1.5 The mechanism I chose for the property pin, and why

New module `tests/test_rendered_command_quoting.py` (18 tests). The property is *every command
string this file renders for shell execution quotes every path it interpolates*, held in two
halves that are cross-checked against each other.

**Half 1 — an AST census, name-independent by construction.** A JoinedStr is censused as a
COMMAND RENDER when either:

- **(i) it reaches a shell SINK** — it is the value of a `"command"` key in a dict literal, or is
  passed to a call with `shell=True`, or follows `-c`/`/c` in an argv list; or
- **(ii) it has the `<interpreter> <script>` SHAPE** — two path-valued interpolations separated by
  nothing but whitespace and quote characters.

"Path-valued" is decided **by the shape of the expression**: `Path(...)`, any
`.as_posix()/.resolve()/.absolute()/.expanduser()` call, `sys.executable`, the module globals
`INSTALL_ROOT`/`FLEET_HOME`, or a call to a helper in the same file annotated `-> Path`. Names
participate only as an *alias step* — a name resolves to the expression it was assigned — so
`py`, `interp` and `zzz` are indistinguishable to it.

**Why not a widened regex or a longer name list.** Both are the same defect one notch further out.
The gate proved a rename defeats a name list; a name list with three more names is defeated by the
fourth name. Deciding on the *expression's shape* removes names from the question entirely.

**Why the unit is the rendered LINE and not the f-string.** **MEASURED** — this correction was
forced by a false positive. Censusing per f-string flagged `_render_sup_spawn_task:17134`
(`running in {FLEET_HOME.as_posix()} (three-tier §10.1)`), which is prose six lines above the
`sup-boot` command line in the same triple-quoted body, and correctly unquoted because no shell
ever reads it. **The scan was wrong, not the tree**, and it was narrowed until the shipped tree was
clean.

**Why a naive "every path interpolation must be quoted" rule is unshippable.** **MEASURED**, with
the predicate this module actually ships: `bin/fleet.py` holds **142** path interpolations,
**120 of them unquoted**, and essentially all of the 120 are prose, prints and error messages
(`f"registry unreadable: {path}"`). A pin that demanded quotes there would be suppressed within a
day and would then hold nothing. *(An earlier exploratory scan with a looser predicate — it also
followed `for` targets and `with` bindings — reported 165/145. The shipped numbers are the ones
above; the looser scan is not what any test uses.)*

**Half 2 — behavioural, over the census.** Every censused render is driven with a real space in
the interpreter path *and* in both roots, and the emitted command lines are re-parsed with
`shlex` — the consumer's own parser, not a regex that agrees with the bug. Each driver asserts it
**reached its own site** (a line carrying the spaced interpreter must exist, else the test fails
with "the fixture never reached the render"), which is the wave-35 mutant "a driver repointed at
another path". `test_every_censused_render_has_a_driver` asserts census-set == driver-set in both
directions, so a render added tomorrow cannot escape the behavioural half by simply not having a
test written for it.

### 1.6 The four requirements, each with its mutant

**MEASURED.** All against post-fix `bin/fleet.py` sha256
`23e6b1ee25c26df7e4e53c3fb107c03dcfefcd0fd5b9dd17e026caab9d8d254a`; every run restored
byte-identically.

| mutant | old name-scoped pin | new property pin |
|---|---|---|
| unquote a render, names kept | rc=1 RED | rc=1, **2 failed** |
| unquote a render, **renamed** `{interp}`/`{script_path}` | rc=0 **GREEN** | rc=1, **2 failed** |
| **the shipped `_install_statusline` defect restored** | rc=0 **GREEN** | rc=1, **2 failed** |
| **a fifth render written today** with names nothing has seen (`zzz`, `qqq`) | rc=0 **GREEN** | rc=1, **4 failed** |
| *(none — the shipped tree)* | rc=0 | **18 passed, zero false positives** |

Requirement 4 is the one worth reading twice: the census flags **nothing** on the shipped tree, and
the one thing it did flag before narrowing was adjudicated as a scan defect with the source line
quoted, not silenced.

### 1.7 Census of the sibling renders — is there a fifth?

**MEASURED, AST-derived** over every `*.py` under `bin/` (glob, so a new module cannot escape by
not being listed):

| site | function | unquoted paths, after the fix |
|---|---|---|
| `bin/fleet.py:6134` | `_install_statusline` | none *(was 2 — this lane's defect)* |
| `bin/fleet.py:9102` | `_steer_supervisor_release` | none |
| `bin/fleet.py:17134` | `_render_sup_spawn_task` | none |
| `bin/fleet.py:17378` | `_render_successor_task` | none |

Files scanned: `fleet.py`, `fleet_statusline.py`, `postcompact_journal.py`,
`posttooluse_mailbox.py`, `stop_mailbox.py`, `stop_outcome.py`.

**There is no fifth f-string render.** `_install_statusline` was the fourth and it was the broken
one.

**But there IS a fifth SURFACE, and it is not an f-string.**
`worker-settings.template.json` renders four hook `command` strings through
`render_worker_settings_template()`'s `{{PYTHON}}`/`{{FLEET_INSTALL}}`/`{{FLEET_HOME}}`
substitution. The AST census over `bin/**/*.py` **cannot see it at all**. **MEASURED:** all four
hook commands already quote all three placeholders, and the property is now pinned there too —
statically over the template text, and behaviourally by rendering with spaced roots and
`shlex`-splitting the result (`TestTheTemplateSurfaceQuotesToo`).

### 1.8 How the quoting rule meets `CLAUDE.md`'s forward-slash rule

**MEASURED**, in git-bash:

```
$ bash -c 'echo "C:\Users\Techn\x"; echo C:\Users\Techn\x'
C:\Users\Techn\x
C:UsersTechnx
```

They are two fixes for two different behaviours of the same consumer and they do not conflict.
A double-quoted segment keeps its backslashes; an unquoted one loses them — so **quoting is the
stronger property and subsumes the backslash hazard for the paths it wraps**. Forward slashes stay
required: the rendered value is written into JSON other tooling reads, and the rule is stated in
the SPEC. Nothing in this lane weakens it.

### 1.9 The `--chain` path — the brief's own flagged unknown

**MEASURED, by reading `bin/fleet_statusline.py` and `_install_statusline`.** There is **no
interaction**, in either direction:

- `_run_delegate` runs a captured incumbent with `shell=True`, **verbatim**. Fleet neither adds nor
  removes quoting from a delegate; a delegate that was already broken stays broken and one that was
  correct stays correct. Not this lane's defect and not made worse by the fix.
- A fleet-owned incumbent is never chained: `foreign = bool(incumbent) and "fleet_statusline.py"
  not in incumbent`. The pre-fix broken string still contains `fleet_statusline.py`, so an operator
  re-running `fleet init --statusline --chain` on a machine carrying the broken command gets a
  re-install, not a self-invoking chain. **MEASURED by inspection of the string, not by driving
  `--chain`.**

**FILED, not fixed:** `_capture_statusline_delegate` stores whatever the incumbent was, and
nothing validates it. That is out of this lane's scope and is a property of somebody else's
statusline, not of fleet's render.

---

## PART 2 — the check count, and a receipt that was wrong the whole time

### 2.1 What the tree actually says

**MEASURED**, three independent ways, all agreeing:

```
$ grep -c "def _doctor_check_" bin/fleet.py
28
$ # cmd_doctor's check_calls list, by AST
28
$ fleet doctor  (throwaway home) | grep -cE '^\[(PASS|FAIL|WARN)\]'
28
```

**MEASURED:** the 28 definitions and the 28 registrations are the *same 28 names* — no check is
defined and unwired, and none is registered without a definition. That is checked, not assumed;
the two measurements are not interchangeable in general and `tests/test_doc_claims.py` correctly
prefers the registrations.

### 2.2 Why the three instruments were blind — with one correction

1. **The pin's regex.** **MEASURED**, driving the shipped detector directly:

   ```
   '23 checks'            -> [23]
   '**23** checks'        -> []          <-- the shipped form
   '*23* checks'          -> []
   'checks: 28'           -> []
   '28 doctor checks'     -> []
   'the 23 health checks' -> [23]
   ```

   The brief's diagnosis is **correct**: `\d+\s+` cannot reach across the `**` that sits between
   the digits and the space, so the bold form defeats the pin's own matcher exactly as it defeated
   the ad-hoc `grep -E`.

2. **THE REASON THE BRIEF DID NOT NAME, and it is the primary one.** **MEASURED:**
   `ENTRY_DOCS` is `("README.md", "docs/getting-started.md", "docs/concepts.md", "docs/README.md",
   "CONTRIBUTING.md", "docs/launch-readiness.md")`. **`docs/SPEC.md` is not on it.** The claim would
   have escaped this pin *written in plain text*. The markup hole and the scope hole are
   independent, and the scope hole would have held on its own.

3. **The receipt harness.** **MEASURED by reading it**, as the brief asked: `tests/test_receipts.py`
   sets `SPEC_DIR = REPO / "docs" / "specs"` and enumerates `SPEC_DIR.glob("*.md")`.
   `docs/SPEC.md` is not in that directory. The scope claim is confirmed.

### 2.3 The population, derived and classified

**MEASURED.** Scanned every tracked `*.md` (140 files) with a markup-stripping matcher covering
`<N> checks`, `<N> doctor/health/fleet checks`, `checks: <N>`, `checks -> <N>` and `N PASS / M FAIL`.
**105 hits.**

**Current-tree surfaces — 11 hits, 3 initially wrong:**

| site | phrasing | value | verdict |
|---|---|---|---|
| `README.md:87` | `28 health checks` | 28 | correct |
| `README.md:121` | `28 checks` | 28 | correct |
| `README.md:155` | `28 fleet health checks` | 28 | correct |
| `docs/getting-started.md:143` | `28 checks` | 28 | correct |
| `docs/getting-started.md:145` | `28 PASS / 0 FAIL` | 28 | correct |
| `docs/getting-started.md:289` | `28 health checks` | 28 | correct |
| `docs/launch-readiness.md:282` | `28 checks` | 28 | correct |
| `docs/launch-readiness.md:283` | `28 PASS / 0 FAIL` | 28 | correct |
| **`docs/SPEC.md:281`** | `**23** checks` | 23 | **ROT — fixed** |
| **`docs/SPEC.md:17`** | `check count (21 → 23)` | 23 | **ROT — fixed** |
| `CONTRIBUTING.md:41` | `it drifted twice — 21→23 … against an actual 28` | — | **TRUE HISTORY — not touched** |

**MEASURED — the nine-site floor.** The gate counted nine sites. I derived the population myself
and found **exactly two current-tree sites still wrong**, both in `docs/SPEC.md`; the other
previously-counted sites now read 28 (measured above, three files). So nine was a floor for the
*campaign*, and by the time this lane ran, seven of them had already been fixed by w48/w49 and two
had not. I did not find a tenth current-tree site. **BELIEVED:** that the seven were fixed by those
waves specifically — I measured only that they are correct now, not who corrected them.

**`CONTRIBUTING.md:41` is the interesting classification and I did not fix it.** It reads *"The
check count is why: it drifted twice — `21`→`23` fixed by hand in 2026-07-23's doc pass, rotted to
`25`/`22`/`23` against an actual `28` two weeks later."* Every number in it is a dated historical
claim and the number it states as current — 28 — is right. My first arrow-matcher fired on it;
**that was the matcher's false positive, not rot.** Per the ratified 2026-08-05 rule, a quoted
argument about a past tree stays true and fixing it fabricates.

**Historical surfaces — 94 hits across 21 files, exempt and NOT fixed.** Classified by path
pattern, not by enumeration, so tomorrow's lane report is exempt by construction:
`docs/lanes/`, `docs/reviews/`, `docs/proposals/`, `docs/superpowers/`, `docs/decisions/`,
`docs/specs/`, `docs/AUTONOMOUS-*`, `docs/OVERNIGHT-*`, `docs/mf-*`, `spike/`, `FIX-WAVE-*`,
`REVIEW-INPUT-*`, `docs/PLAN.md`, `docs/PLAN-PROGRESS.md`, `docs/NEXT-SESSION.md`,
`docs/SPEC-v2-history.md`, `docs/OPERATOR-GATES.md`, `docs/IDEA-FORGE-REPORT.md`,
`docs/PRIOR-ART.md`, `docs/longcat-fleet-usage.md`, `knowledge/`, `supervisor/`.

**MEASURED, the clearest case:** `docs/OPERATOR-GATES.md:24` quotes both `29 checks` and
`23 checks` inside an argument whose own prose says *"where the truth is 28"*. It is an argument
**about** the count. Editing the quoted numbers would destroy the argument and fabricate a history
that did not happen.

### 2.4 The widened pin

- **Markup is removed before matching, not enumerated in the pattern.** `*`, `` ` `` and `~` are
  stripped wholesale; `_` only where it wraps a bare number, because `_` is a word character and
  `_doctor_check_` is the very token this pin derives from (pinned by a seed).
- **Phrasings**: `<N> checks`, `<N> fleet/doctor/doctor's/health checks`, `checks: <N>`,
  `checks = <N>`, `checks → <N>`, `checks -> <N>`, and `N PASS / M FAIL` (now also markup-blind).
- **The qualifier set is CLOSED** (`fleet`/`doctor`/`health`) and that narrowing is **MEASURED**:
  an open `(?:\w+\s+){0,2}` gap matched `4 demand check`, `9 redefine check`, `6 SPURIOUS-FIX
  check`, `4493 builds checks` and eight more unrelated sites. A pin that cries wolf gets
  suppressed and then holds nothing. All twelve are pinned in the seed test as **must-not-fire**.
- **The file population is DERIVED**: every tracked `*.md` minus `_HISTORICAL_PREFIXES`.
  **MEASURED: 27 of 140 files.** This is the fix for the reason the brief did not name.

### 2.5 The mutants — each variant planted and watched

**MEASURED.** Ten document mutants, each asserting `occurrences == 1` before running, printing
sha256 before/after, restoring and verifying:

| mutant | file | result |
|---|---|---|
| `**23** checks` | README.md | **RED** (1 failed) |
| `*23* checks` | README.md | **RED** |
| `_23_ checks` | README.md | **RED** |
| `` `23` checks `` | README.md | **RED** |
| `checks: 23` | README.md | **RED** |
| `23 doctor checks` | README.md | **RED** |
| `checks -> 23` | README.md | **RED** |
| `**25 PASS / 0 FAIL**` | docs/getting-started.md | **RED** |
| `**23** checks` in a file never in `ENTRY_DOCS` | skills/fleet/SKILL.md | **RED** ← the scope mutant |
| `**23** checks` in dated history | docs/lanes/w48-c.md | **GREEN** ← the control |

The last row is the point of the classification: the widened pin must *not* fire on a quoted
argument about a past tree.

### 2.6 The `docs/SPEC.md` fix — a roster, not just a number

**MEASURED, and this is a finding the brief did not have.** §13 did not merely *state* 23 — it
**enumerated 23 checks by name**. The number and the roster were wrong together, which is exactly
why the delta reconstructs cleanly instead of needing invention. Diffing the enumeration against
`cmd_doctor`'s registrations gives the five it never gained, each with the commit that added it
(`git log -S "def _doctor_check_<name>"`):

| check | added by |
|---|---|
| `registry` | `875a46c` |
| `instance_grants` | `9f7fe26` |
| `permission_stalls` | `1b97efb` |
| `identity_witness` | `bd3dfd2` |
| `supervisor_wedge` | `346a747` |

**23 + 5 = 28.** No part of this history is remembered or reconstructed from prose. The
parenthetical was not blanked: it now carries `21 → 22 → 23 → 28` with the reason for each move,
the roster names all 28 in registration order, and the two FAIL-capable rows the old text implied
were note-only (`permission_stalls`, `supervisor_wedge`) are named as FAIL. **MEASURED:** a script
diffing the new roster's backticked names against the registrations reports `MISSING from roster:
[]`, 28 of 28.

`docs/SPEC.md:17`'s `(21 → 23)` was rewritten to state `28 checks` in the canonical phrasing —
which **puts it back under the pin** rather than leaving it as an unheld hand-maintained line.

**One thing the widened pin caught immediately: my own new prose.** My first draft of the fix
wrote *"its roster below listed 23 checks by name"* — a historical statement in the canonical
form. The pin went RED on it. I rephrased the prose ("named only 23 of them") rather than
weakening the pin.

### 2.7 What the widened pin still exempts — the census, shipped in its docstring

Per wave 45 (*any pin shipping a carve-out ships the census of what it exempts*), and per the
observation that this pin's docstring has now twice named the exact hole that later shipped a
defect:

- **Dated history**, by path pattern — 94 hits, 21 files. Fixing them would fabricate.
- **The `N → M` drift narrative**, in every file. `CONTRIBUTING.md:41` and `docs/SPEC.md:17` wore
  the identical shape and one was true history while the other was stale. **No regex separates
  them**, so neither is held; SPEC.md:17 was fixed by hand and re-anchored to a canonical claim.
- **Prose ending in "check"** — the closed qualifier set makes `the pending_decision check`
  invisible.
- **ABSENCE**, still — a document that never states the count is green.
- **The pasted receipt TEXT.** `docs/SPEC.md`'s `grep -c … → 28` is held only as a *number*.
  `tools/verify_receipts.py` does not reach `docs/SPEC.md`, so if the grep's output and the
  registrations ever diverge, this pin follows the registrations and the pasted arrow rots
  silently. **FILED, not fixed** — bringing `docs/SPEC.md` under the receipt harness is a campaign
  (every receipt in it must be re-pinned to a sha), which `docs/SPEC.md:19` already says out loud.
- **Shapes 1 and 3 (verbs, Python floor) were NOT widened** — still `ENTRY_DOCS` only. Widening
  them needs its own false-positive measurement and this lane was the check count. A `fleet
  frobnicate` in `skills/fleet/SKILL.md` remains unheld. **Stated, not silently narrowed.**

---

## 3. Floors

**PREDICTION, written before either run:** 4299 collected on both interpreters, **0 failed** on
both, tree sha256 `ac7899b4…` identical before and after each run.

**MEASURED.** Collection derived with `--collect-only` on each interpreter separately, never by
arithmetic on a diff:

```
py -3.13 -m pytest --collect-only -q   ->  4299 tests collected
py -3.10 -m pytest --collect-only -q   ->  4299 tests collected
```

Floors, run back to back on the same tree:

```
py -3.13 -m pytest -q   ->  4284 passed, 14 skipped, 1 xfailed in 444.07s   rc=0
py -3.10 -m pytest -q   ->  4284 passed, 14 skipped, 1 xfailed in 398.48s   rc=0
```

4284 + 14 + 1 = **4299**. **The prediction held on both sides.** I predicted the collection count
and zero failures; I did not predict the skip/xfail split numerically, and it is identical on both
interpreters. The 3.10 run is the one that matters for the floor — `fleet.MIN_PYTHON_VERSION` is
(3, 10) and 3.13 is only this machine's preference.

Tree identity, hashed over all 241 tracked files plus the new untracked test module, at three
points — before 3.13, between the runs, after 3.10:

```
s2-before  tree_sha256=ac7899b436a541d314f86a30a496af0394e7ef44efb89b468db0a496e156e688
s2-mid     tree_sha256=ac7899b436a541d314f86a30a496af0394e7ef44efb89b468db0a496e156e688
s2-after   tree_sha256=ac7899b436a541d314f86a30a496af0394e7ef44efb89b468db0a496e156e688
```

**No floor was started with a mutant on disk.** Every mutant run in this lane printed its own
before/after sha256 and reported `RESTORED=YES`, and `git status` was checked after each batch
(§4.8 records the one time that mattered).

**The collection delta from base, derived rather than computed.** A detached worktree at `4d78f6c`
was created under the job tmp dir purely to run `--collect-only` there, and removed afterwards:

| tree | 3.13 | 3.10 |
|---|---|---|
| base `4d78f6c` | 4238 | 4238 |
| this branch | 4299 | 4299 |

**+61**, and every one is accounted for by per-module collection, not by subtraction:
`tests/test_rendered_command_quoting.py` is **+18** (new module); `tests/test_doc_claims.py` goes
**26 → 69**, which is **+42** from re-parametrizing two tests over 27 `CHECK_COUNT_DOCS` instead of
6 `ENTRY_DOCS` (2 × 21) plus **+1** new population seed. 18 + 42 + 1 = 61.

**A runtime cost I introduced and then paid down.** Widening the check-count pin from 6 documents
to 27 made `tests/test_doc_claims.py` call `_registered_doctor_checks()` ~54 times per run, each
re-parsing 21,453 lines of `bin/fleet.py`. **MEASURED: the module took 67.35s.** Adding
`functools.lru_cache` to the three derivations (`_registered_doctor_checks`, `_shipped_verbs`,
`_tracked_markdown`) brought that module plus the new one to **6.91s combined**. Caching is
per-process and every mutant planter starts a fresh pytest process, so no mutant can be masked by
it — re-verified after the change: `readme_bold` still **RED**, `lane_historical` still **GREEN**,
`unfix_statusline` still **RED**.

**Scope note, stated rather than glossed:** the floors ran on the shipped tree with one exception —
this report's own §3, which is the paragraph you are reading. No test reads it: it was untracked
during the floors, and once committed it lives under `docs/lanes/`, which
`_HISTORICAL_PREFIXES` exempts by construction. That exemption is verified after the commit rather
than assumed (§6).

---

*(Section numbering: the brief-correction section is §4 below; its numbered items are referenced
as §4.N.)*

## 4. WHERE THIS BRIEF WAS WRONG

1. **"Quoting `_install_statusline` is a clean one-line fix" — RIGHT, and the flagged `--chain`
   risk is real but empty.** It is one line, inserts nothing, and leaves `bin/fleet.py` at 21453
   lines. `--chain` does not interact: fleet passes a delegate verbatim, and a fleet-owned
   incumbent is detected by substring and re-installed rather than chained. The brief was right to
   flag it as unexamined; the examination came back clean.

2. **"README quickstart step 4" — CONFIRMED**, with the qualification that the step is labelled
   "Optional".

3. **"The bold form is why `docs/SPEC.md` escaped the pin" — HALF RIGHT, AND THE MISSING HALF IS
   THE ONE THAT MATTERS.** The brief predicted this line might need correcting, and it does. Bold
   *does* defeat the pin's own matcher (measured, `find_check_count_claims("**23** checks") == []`).
   But **`docs/SPEC.md` was never in `ENTRY_DOCS`**, so the claim would have escaped written in
   plain text. Two independent holes; the file-scope one is primary and the brief named only the
   markup one. Fixing only the regex would have left the defect fully intact.

4. **"28 is stable" — HELD.** This lane added and removed no doctor check; 28 at the start and 28
   at the end, re-measured after all edits.

5. **"These two parts are one shape" — CONFIRMED, and the shared mechanism is real.** Both defects
   are the same sentence: *a pin's SCOPE is a claim, and an unmeasured scope claim is false.* In
   Part 1 the scope was two placeholder **names**; in Part 2 it was one **phrasing** and six
   **filenames**. Both were fixed the same way — **replace the enumeration with a derivation, then
   attack the derivation with the mutant that the enumeration would have missed.** Part 1 derives
   command renders by AST from expression *shape*; Part 2 derives its file population by glob-minus-
   pattern and its claims by markup-stripped phrasing family. Both ship the census of what they
   still exempt. I did not build a single shared instrument — the two surfaces are Python AST and
   markdown prose and a common tool would fit neither — but the **discipline** is shared and both
   pins now state their own scope as a measured claim rather than an implied one.

**Corrections the brief did not anticipate:**

6. **The gate's `cmd` receipt is not discriminating as stated.** Under bare `cmd /c`, the quoted
   control fails too (rc 1), because `/c` without `/s` strips the line's outer quote pair. The
   correct cmd-side control needs `cmd /d /s /c "<command>"`. The finding stands; the receipt
   needed a better arm.

7. **`docs/SPEC.md` §13 was a wrong ROSTER, not only a wrong number.** It enumerated 23 checks by
   name. Anyone fixing only the digits would have left a section titled *"Doctor roster — as it is
   today"* five checks short, and the pin (which reads numbers) would have been green.

8. **A `finally`-based mutant restore is not sufficient.** A wrapper timeout SIGKILLed the doc-
   mutant loop between mutants and left `skills/fleet/SKILL.md` mutated on disk; the `finally`
   never ran. `git status` immediately after the batch caught it and it was restored before any
   floor started. **`git status` after every mutant batch is the guard; the `finally` is only the
   happy path.**

---

## 5. What this lane did NOT do

- Did not widen the verb pin or the Python-floor pin (§2.7).
- Did not bring `docs/SPEC.md` under `tools/verify_receipts.py` (§2.7) — that is a campaign.
- Did not touch any historical document (§2.3), by design.
- Did not add validation of a captured `--chain` delegate (§1.9).
- Did not change any doctor check, so the count is untouched at 28.

---

## 6. Post-commit verification

**MEASURED after committing**, because §3's scope note is a claim and this is its check: with
`docs/lanes/w50-launchfix.md` tracked, `_tracked_markdown()` sees it, `_HISTORICAL_PREFIXES`
excludes it (`docs/lanes/`), and `CHECK_COUNT_DOCS` is unchanged at 27 of 141. This report quotes
`**23** checks`, `checks: 23` and `23 doctor checks` verbatim as mutant descriptions — every one of
which the widened pin is built to catch — and the pin stays green *because the pattern-based
exemption is doing exactly the job it was designed for*. Numbers and the pin re-run are appended
below.
