# w48 gate — adversarial review of `w48/launch-rehearsal`

# GATING

**Under gate:** branch `w48/launch-rehearsal`, single commit `4ccc8f7`, 5 files, +645/−17.
**Gate lane:** `w48/glaunch`, worktree `C:/proga/fleet-w48-glaunch`, cut at `4ccc8f7`.
**Merge-base:** `fa236cb` (== `main` tip). `git merge-base w48/launch-rehearsal main` → `fa236cb`.
**Tally:** 0 BLOCKING, 3 MAJOR, 4 MINOR. Every claim the brief named was re-driven; the three
headline claims all came back TRUE.

**Why GATING and not GREEN:** the three MAJORs are all sentences *this commit added* to the two
entry docs, and each describes behaviour that does not exist or prescribes a remedy that does not
cover the cause. That is precisely the failure mode the brief called highest-value — *"a doc that
was wrong in one direction and is now wrong in the other is a worse outcome than the original,
because it has a fresh measurement's authority attached."*

**Why not RED:** the branch is a large net improvement. Claims 1, 2 and 3 re-drove true from
independent clones, the numbers all reproduce, the repo fence held exactly, and nothing on the live
machine was harmed. Fix the three MAJORs and this should land.

---

## METHOD NOTES THE BRIEF REQUIRED

- **MEASURED vs BELIEVED is marked on every line below.** No BELIEVED line carries a BLOCKING or
  MAJOR grade.
- **Every measurement whose good answer is zero/empty was run against a known non-zero control
  first, and the control is shown inline each time.** Controls run: the fence path-probe against a
  commit that *does* touch `bin/` (returned `bin/fleet.py`, `tests/test_core.py`); the subcommand
  counter against a synthetic 3-item list (returned 3); the table-coverage `comm` against a planted
  missing verb (returned `homes`); the link checker against a seeded bad path *and* a seeded bad
  anchor (returned exactly 2); the population probe against both an absent homes list and an
  unclaimed sid; the `fleet home` gate before every scratch-home command.
- **No run whose evidence is its whole output was piped through `head`/`tail`.** The two pytest
  selections, both `fleet doctor` runs and `claude plugin marketplace list` are quoted whole or
  counted mechanically from the whole captured file.
- Output is quoted verbatim.

---

## FLEET-COMMAND AUDIT — every `fleet` command I ran, and which home it actually touched

The brief asked for this explicitly. **No `fleet` verb was run against `C:/proga/claude-fleet`.**

Every invocation went through a **temp clone's own shim**, with `fleet home` run first and its
answer compared against the expected temp path before any other verb was allowed to run — and on a
machine where `~/.claude/fleet-homes.list` was verified ABSENT immediately beforehand (which,
per Finding 1, is the precondition that actually makes that discipline safe).

| Command | Home it acted on | Effect |
|---|---|---|
| `py -3.1{0,3} bin/fleet.py --help`, `py -3.{8,12} …` | none — argparse/launcher exits first | read-only |
| `fleet home` ×6 (temp clones `gate/old/fleet`, `gate/new/fleet`, `scratch2`) | those temp paths | read-only |
| `fleet home` with PATH stripped | none — `CommandNotFoundException`, nothing executed | none |
| `fleet knowledge` ×2 | `…/tmp/scratch2` | read-only, rc=0 |
| **`fleet init` ×1** | **`…/tmp/scratch2`** | **the only write by any fleet verb in this gate** — wrote `scratch2\state\worker-settings.json` |
| `fleet --fleet-home …/scratch2 home` | none — refused `not_initialized`, *"Nothing was created"* | none |
| `fleet spawn probe --dir . --task "noop" --max-budget-usd 5` | `…/tmp/scratch2` | refused pre-dispatch, rc=1, no registry created |
| `fleet homes` | reads `~/.claude/fleet-homes.list` (absent) | read-only; list still absent after |
| `fleet homes --help`, `fleet spawn --help` | none | read-only |
| `fleet doctor` ×2 | `…/tmp/scratch2` | report-only, rc=0 then rc=1 |
| in-process `resolution_population` / `resolve_home` / `lookup_home_for_sid` | none — `homes_list_path` monkeypatched to a temp file | the real list was never read or written |

My only write to the live home was the task-mandated journal at
`C:/proga/claude-fleet/state/journals/w48-glaunch.md`.

---

# FINDINGS

## MAJOR-1 — `docs/getting-started.md:97`: the sid-lookup population is **not** install-root-scoped, and the sentence saying it is teaches an unsafe fence

**MEASURED.** The new precedence table says:

```
| 2 | this session's id, looked up against the registries the install root can see | the session id is claimed by one of them |
```

`bin/fleet.py:4589` says otherwise. `resolution_population()` is the **machine-wide homes list ∪
the install root**:

```python
def resolution_population(install=None) -> dict:
    ...
    listed = read_homes_list()          # ~/.claude/fleet-homes.list  -- machine-global
    legacy = home_identity(install)
    homes, seen = [], set()
    for ident in list(listed["members"]) + [legacy]:
```

The install root does not gate the listed members; it is merely appended as one more candidate.
Driven as a pure function, with both controls, `homes_list_path` redirected to a temp file so the
real list was never touched:

```console
REAL homes list path this build would use: C:\Users\Techn\.claude\fleet-homes.list
REAL list exists: False

=== CONTROL A: homes list ABSENT/EMPTY (this machine's actual state) ===
--- install=installX, sid claimed only by homeY, FLEET_HOME=homeZ
    population        = ['C:/Users/Techn/.claude/jobs/ed03cd54/tmp/probe/installX']
    lookup.state      = miss
    resolve_home.step = env
    resolve_home.home = C:\Users\Techn\.claude\jobs\ed03cd54\tmp\probe\homeZ

=== CONTROL B (positive control for the detector): sid nobody claims ===
--- install=installX, sid=<unclaimed uuid>, FLEET_HOME=homeZ
    population        = ['C:/Users/Techn/.claude/jobs/ed03cd54/tmp/probe/homeY', 'C:/Users/Techn/.claude/jobs/ed03cd54/tmp/probe/installX']
    lookup.state      = miss
    resolve_home.step = env
    resolve_home.home = C:\Users\Techn\.claude\jobs\ed03cd54\tmp\probe\homeZ

=== TEST: homes list contains homeY; install root is installX ===
--- install=installX, sid claimed by homeY, FLEET_HOME=homeZ
    population        = ['C:/Users/Techn/.claude/jobs/ed03cd54/tmp/probe/homeY', 'C:/Users/Techn/.claude/jobs/ed03cd54/tmp/probe/installX']
    lookup.state      = hit
    resolve_home.step = lookup
    resolve_home.home = C:\Users\Techn\.claude\jobs\ed03cd54\tmp\probe\homeY

VERDICT:
  homeY in population despite install root being installX?  True
  FLEET_HOME(homeZ) ignored in favour of homeY?             True
```

Control A is why the lane's reading looked right: with `fleet-homes.list` absent — this machine's
actual state, verified before and after — the population *collapses to exactly the install root*, so
install-root scoping is observationally true on a single-fleet box. It is not the rule. The lane
graded this half BELIEVED in its own §3 (*"BELIEVED (read from source, not separately executed): the
lookup population is scoped by `INSTALL_ROOT`"*) and the doc then states it as fact.

**Why this is MAJOR and not a wording nit — it invalidates the safety advice built on top of it.**
Lane report §12 tells the next lane:

> **The correct primitives are `--fleet-home <PATH>`, or the target clone's own shim — not the env
> var.** The next lane that runs an installer on this machine should be briefed with that.

The second primitive is conditional and the condition is unstated. A temp clone's own shim fences
only while `~/.claude/fleet-homes.list` is absent. Register one home and the temp clone's shim sees
it, the sid lookup hits, and `FLEET_HOME` is ignored *from the temp clone too* — the fence silently
stops working, with no error, which is the 2026-07-29 incident's exact shape. **And this same commit
newly documents `fleet homes --add` in both command tables** (`README.md:154`,
`docs/getting-started.md:273`) — it advertises the verb that disarms its own safety advice.

I relied on that discipline myself, and it was sound *only because* I verified the list absent
first. That verification is the step the advice omits.

**Fix:** row 2 should read something like *"this session's id, looked up against every home in
`~/.claude/fleet-homes.list` plus this install root"*, and §12's second primitive needs
*"…and only while `~/.claude/fleet-homes.list` is empty — check it first."*

---

## MAJOR-2 — `README.md:113` + `docs/getting-started.md:55`: `# a DIRECTORY path, not a URL` asserts a restriction the shipped CLI contradicts

**MEASURED.** This is attack B, and the disclosed caveat turns out to be wrong in a way disclosure
does not cover. Both docs now ship:

```
claude plugin marketplace add C:\path\to\this\clone   # a DIRECTORY path, not a URL
```

The command's own help:

```console
$ claude plugin marketplace add --help
Usage: claude plugin marketplace add [options] <source>

Add a marketplace from a URL, path, or GitHub repo
```

A URL is an accepted source form. And the evidence was already on screen in the very output the
lane read — the full, unabridged listing:

```console
$ claude plugin marketplace list
Configured marketplaces:

  ❯ claude-plugins-official
    Source: GitHub (anthropics/claude-plugins-official)

  ❯ openai-codex
    Source: GitHub (openai/codex-plugin-cc)

  ❯ caveman
    Source: GitHub (JuliusBrussee/caveman)

  ❯ claude-fleet
    Source: Directory (C:\proga\claude-fleet)

  ❯ cc-oracle
    Source: GitHub (exPardus/cc-oracle)
```

Four of the five marketplaces on this machine are GitHub-sourced. So the follow-on claim at
`docs/getting-started.md:82` — *"Whether the `owner/repo` GitHub shorthand also works is
untested"* — and at `docs/launch-readiness.md:80` — *"whether the `exPardus/fleet` GitHub shorthand
also works — **no evidence either way**"* — are both false. There is evidence, in the pasted output
and in `--help`, that this CLI takes GitHub shorthand; what remains genuinely untested is only
whether `exPardus/fleet` in particular resolves as a marketplace.

**The half that IS right, confirmed:** the directory form is correct. `claude-fleet` is really
installed from `Source: Directory (C:\proga\claude-fleet)`, that path is really a directory
(`IS_DIR=yes`), and `.claude-plugin/marketplace.json` really declares plugin `fleet` at
`"source": "./"`. The replacement literal works; the parenthetical attached to it does not.

**Fix:** drop *"not a URL"*; say the directory path is the form verified here, and that `--help`
documents URL and GitHub-repo forms as well, untested for this repo.

---

## MAJOR-3 — `README.md:128` + `docs/getting-started.md:77`: "fix PATH" is prescribed for a symptom that `FLEET_HOME` also causes

**MEASURED.** Both new callouts end by naming exactly one cause:

> README:128 — *"If it prints something other than your new clone, **fix PATH** before running `fleet init`."*
> getting-started:77 — *"If the answer is not the clone you just made, **fix PATH first**."*

PATH is not the only cause, and the same document says so 20 lines later (the priority table lists
`FLEET_HOME` at priority 3). Driven with PATH *correct* — the new clone's own shim, zero other fleet
entries — and only `FLEET_HOME` left over from a prior install:

```console
=== E3. Step 1 followed EXACTLY; no other fleet on PATH; but FLEET_HOME set from a prior install ===
Get-Command fleet -> C:\Users\Techn\.claude\jobs\ed03cd54\tmp\gate\new\fleet\bin\fleet.cmd
FLEET_HOME        = C:\Users\Techn\.claude\jobs\ed03cd54\tmp\gate\old\fleet
cwd               = C:\Users\Techn\.claude\jobs\ed03cd54\tmp\gate\new\fleet
fleet home ->
C:/Users/Techn/.claude/jobs/ed03cd54/tmp/gate/old/fleet
rc=0

=== E3b. CONTROL: same shell, FLEET_HOME removed ===
C:/Users/Techn/.claude/jobs/ed03cd54/tmp/gate/new/fleet
rc=0
```

A reader who hits this and follows the instruction audits PATH, finds it flawless, and is left with
no next step — while `fleet init` would still write into the old home. This is the block whose
entire stated purpose is *"the step that stops the worst mistake"* and *"That has happened here and
cost a real incident."*

Severity is capped below BLOCKING because **detection still works**: the reader sees the wrong home
and stops. Only the remedy under-covers.

**Fix:** *"…check PATH, and check `FLEET_HOME` — either can point you at another home."*

---

## MINOR-4 — the lane's live-`state/` fence receipt is not reproducible on this box

**MEASURED.** Lane §0 asserts:

> `C:/proga/claude-fleet/state` — file-set + size + mtime snapshot compared before and after every
> step that could have touched it. Reported `UNCHANGED` each time.

The live `state/` tree is written continuously by other actors. Measured just now, on the live home:

```console
=== files modified in the last 60 minutes under the live state/ ===
2026-08-09 04:20  state/outcomes/sup~inc-20260808T173831Z-c6d4~boot.jsonl
2026-08-09 04:22  state/briefs/sup~inc-20260808T232220Z-db73~boot.md
2026-08-09 04:23  state/autoclean-last-run.json
2026-08-09 04:26  state/w48-ckpt-01.md
2026-08-09 04:28  state/tasks/lens/w48-c.md
2026-08-09 04:29  state/tasks/lens/w48-launch.md
2026-08-09 04:30  state/briefs/w48-launch.md
2026-08-09 04:33  state/w48-c-steer-01.md
2026-08-09 04:36  state/w48-operator-docket.md
2026-08-09 04:37  state/w48-ckpt-02.md
2026-08-09 04:50  state/journals/w48-launch.md
2026-08-09 05:00  state/fleet.json
2026-08-09 05:00  state/events.jsonl
   … 33 files in total, including state/fleet.json and state/events.jsonl
```

Those timestamps sit **inside the lane's own window** — its `settings.json` check is stamped
`2026-08-09T04:33:55` and the commit is dated `04:49:43`. An honest whole-tree file-set+size+mtime
comparison across that window would have reported CHANGED, repeatedly. So either the snapshot was
scoped far more narrowly than the sentence describes, or the comparison was not sensitive to what it
claims to cover. The lane did positive-control its mutation detector (`detected_change=True`), so
the detector itself is not the problem — the *scope claimed for it* is.

**Graded MINOR, not MAJOR, because the underlying safety conclusion is independently TRUE.** I
confirmed the lane's other live-machine fence claims directly, and they all hold:

```console
=== ~/.claude/settings.json ===
-rw-r--r-- 1 Techn 197609 1859 Aug  8 22:34 /c/Users/Techn/.claude/settings.json
9958041a6ab22cc125fe70968e142fdb */c/Users/Techn/.claude/settings.json
=== ~/.claude/fleet-homes.list ===
ls: cannot access '/c/Users/Techn/.claude/fleet-homes.list': No such file or directory
ABSENT (rc=2)
```

That md5 and mtime are byte-for-byte what the lane recorded in §0 (`md5=9958041A6AB22CC125FE70968E142FDB`,
`mtime=2026-08-08T22:34:02`) — a day later, still unchanged. Also verified: both rehearsal temp dirs
(`Temp\w48-rehearsal`, `Temp\w48-althome`) are **ABSENT** — cleaned up; the `"statusLine"` key in
`settings.json` predates the lane (file unmodified), so it did not install one; the marketplace list
still shows the same five entries with `claude-fleet` Directory-sourced, i.e. no plugin mutation.

The finding is about the receipt, not the conclusion: **the next lane should not reuse
"whole-`state/` snapshot came back UNCHANGED" as a fence receipt on a live fleet** — it cannot mean
what it says.

---

## MINOR-5 — `README.md:125` + `docs/getting-started.md:74`: the `fleet home` callouts justify step 2 with a hazard the new step 1 removes

**MEASURED.** The callouts say:

> README:125 — *"If another fleet clone is already on your PATH, a bare `fleet init` configures
> *that* home, not the one you just cloned"*
> getting-started:74 — *"So if a different fleet clone is already on your PATH, standing inside your
> new clone and typing `fleet init` configures the **other** home"*

Both are true of the *old* walkthrough and false of the new one, because the step 1 this same commit
added **prepends** the new clone. Two fresh temp clones, PATH stripped of every live-fleet entry:

```console
=== E1. CLAIM 1 mechanism: a prior fleet on PATH, standing inside the NEW clone ===
cwd            = C:\Users\Techn\.claude\jobs\ed03cd54\tmp\gate\new\fleet
Get-Command fleet -> C:\Users\Techn\.claude\jobs\ed03cd54\tmp\gate\old\fleet\bin\fleet.cmd
fleet home ->
C:/Users/Techn/.claude/jobs/ed03cd54/tmp/gate/old/fleet
rc=0

=== E2. THE NEW STEP 1 APPLIED: prepend the new clone's bin, prior fleet still present ===
Get-Command fleet -> C:\Users\Techn\.claude\jobs\ed03cd54\tmp\gate\new\fleet\bin\fleet.cmd
fleet home ->
C:/Users/Techn/.claude/jobs/ed03cd54/tmp/gate/new/fleet
rc=0
```

The **instruction** (`fleet home` before `fleet init`) is right and should stay — it still catches
the `FLEET_HOME` cause of MAJOR-3, and it catches the PATH cause for any reader in a later shell who
never re-ran step 1. Only the **stated reason** is now wrong, and it teaches the wrong mental model:
the rule is *PATH order decides*, not *a prior fleet always wins*.

---

## MINOR-6 — `docs/launch-readiness.md:8`: the new disposition sentence silently omits 2 of 9 gaps

**MEASURED.** The added paragraph reads as an exhaustive disposition:

> *"Gaps 1, 3, 4, 6 and 7 reproduced unchanged; gap 2a's open question is answered below; gap 5 was
> not re-checked."*

The document has **8** numbered gaps plus 2a/2b:

```console
$ grep -nE "^#{2,4} " docs/launch-readiness.md
32:### 1. On Windows, the CLI needs Python 3.13 …
52:### 2. Two documented entry steps cannot be executed as written
54:#### 2a. The plugin install step is a placeholder
84:#### 2b. The phrase both docs tell you to say is not a declared trigger
102:### 3. `fleet knowledge` sends you to a command that cannot fix it
126:### 4. `--max-budget-usd` is advertised by `--help` and always refused
139:### 5. There is no CI, so the platform claims can rot silently
155:### 6. The native-contract pin is a local artefact …
180:### 7. One fleet home per machine
192:### 8. `SPEC.md` §18 is stale by two milestones
$ grep -cE "^### [0-9]" docs/launch-readiness.md
8
```

The sentence accounts for 1, 2a, 3, 4, 5, 6, 7 — and never mentions **2b** or **8**. Gap 8 appears
nowhere in the lane report either:

```console
$ grep -niE "gap 8|§18|stale by two" docs/lanes/w48-launch.md docs/launch-readiness.md
docs/launch-readiness.md:192:### 8. `SPEC.md` §18 is stale by two milestones
docs/launch-readiness.md:195:reading §18 as "what works" gets a two-milestone-old picture; …
(no hit in docs/lanes/w48-launch.md)

$ grep -niE "gap 4" docs/lanes/w48-launch.md   # POSITIVE CONTROL — the grep works
346:**Gap 4 re-measured, unchanged.** `--max-budget-usd` is still advertised …
522:| 7 | (a) | MED | `--max-budget-usd` advertised by `--help`, always refused (§7) | …
```

Gap 2b's *substance* was in fact addressed (§9 checked the triggers against `skills/fleet/SKILL.md`
and fixed `concepts.md`), so only the bookkeeping is missing there. Gap 8 is genuinely unaddressed
**and unlisted** — the sentence's only admission of a skip is gap 5. Re-checking whether `SPEC.md`
§18 is stale is a read, so the SPEC fence did not prevent it.

---

## MINOR-7 — attack C: two hunks not licensed by any measurement in the report

I walked the whole diff hunk-by-hunk looking for the measurement behind each. **All but two are
backed**, and I say so as a result, not a formality: the PATH command (§2), the `fleet home` check
(§1), the pasted launcher text (§6), the precedence table (§3), the `not_initialized` paragraph
(§4), the 33-count and `homes` rows (§7), the `concepts.md` trigger caveat (§9), the plugin
directory form (§10) and every `launch-readiness.md` block all trace to a measurement. Two do not:

**(a) `README.md:118` — `#    This writes ~\.claude\settings.json, your machine-wide Claude Code config.`**
Lane §0 states plainly *"**`fleet init --statusline` was never run.**"*, so no measurement in the
report licenses this line. It is nonetheless **TRUE** — `bin/fleet.py:6084` `_install_statusline`
docstring: *"Merge fleet's statusLine into ~/.claude/settings.json (Phase 1.6 D6)"*, and
`path = user_settings_path()` at 6096. It is also a safety warning about a machine-global write,
which is defensible content. Recorded because the brief asked whether the fence held: it leaked, in
a harmless direction, and it leaked from code-reading rather than rehearsal.

**(b) `README.md:133` — internal inconsistency.** The paragraph opens *"**One thing** this quickstart
cannot do for you:"*, then describes two things (the unrehearsed tail past `fleet doctor`, and step
3's argument grade) and closes *"**Both**, with everything else that blocks a first use, are stated
plainly in…"*. Editorial, but it is a changed hunk in the highest-traffic paragraph on the branch.

---

# CLEARED — attacks I ran that did not break it

The brief asked for these to be reported as results. Each was actually executed.

### The three headline claims

**Claim 1 — "bare `fleet init` configures whatever fleet is already on PATH". CONFIRMED, MEASURED,
re-driven independently** from two fresh clones in my own temp dir, never touching the live fleet.
See MINOR-5's E1 block: standing inside the new clone with a prior fleet on PATH, `fleet home`
printed the **old** clone. The mechanism is real and the doc is right to warn about it. I did not run
`fleet init` to prove it; `fleet home` resolves through the identical path and is read-only.

**Claim 2 — "Step 1's PATH line is a comment, not a command". CONFIRMED, MEASURED, and confirmed at
the merge-base as the brief required.** With the strip verified *before* the run:

```console
fleet-bin entries left on stripped PATH: 0
FLEET_HOME is set? False

=== E0. CONTROL: no fleet anywhere on PATH ===
fleet : The term 'fleet' is not recognized as the name of a cmdlet, function, script file, or operable program.
    + CategoryInfo          : ObjectNotFound: (fleet:String) [], CommandNotFoundException
    + FullyQualifiedErrorId : CommandNotFoundException
```

(I ran `fleet home`, not `fleet init` — command resolution fails before any verb runs, so the
mechanism is identical and nothing could have executed against a live home had the strip failed.)

At the merge-base, neither doc contained an executable PATH assignment, with a positive control at
the tip:

```console
=== does either merge-base block contain an executable PATH assignment? (good answer: empty) ===
(none in README@fa236cb)
(none in getting-started@fa236cb)

=== POSITIVE CONTROL: the same grep at 4ccc8f7 (should now find them) ===
102:$env:PATH = "$PWD\bin;$env:PATH"          # this session only
46:$env:PATH = "$PWD\bin;$env:PATH"          # this session only
```

**Claim 3 — the SENTENCES about `FLEET_HOME`. CLEARED on the point the brief flagged.** As
instructed I did not re-prove the mechanism. I read every new sentence about it looking for
bug-framing of ratified behaviour, and **found none**. `docs/launch-readiness.md:16` files it under
*"All three are **prose defects**, now fixed in `README.md` and `docs/getting-started.md`"*;
`docs/getting-started.md:96–100` is purely descriptive (*"the one case where the environment
variable loses"*, *"For an ordinary user, priority 2 never fires"*); the lane report §3 grades it
*"Class (a) — the doc says something false"*, i.e. against the doc, not the code. No sentence on the
branch implies a code defect. The table's *content* is separately wrong at row 2 — that is MAJOR-1,
a different charge.

Two smaller things about that table, both **correct as written** and worth recording since I
checked: `--fleet-home` really does require an initialized home, and the doc's caveat about it is
exact —

```console
$ fleet --fleet-home C:\Users\Techn\.claude\jobs\ed03cd54\tmp\scratch2 home
fleet: --fleet-home C:\Users\Techn\.claude\jobs\ed03cd54\tmp\scratch2 is not initialized (not_initialized) -- an initialized home is one whose `state/fleet.json` exists and parses (docs/specs/multi-fleet.md, Definitions). Nothing was created.
rc=1
```

— and `fleet init` really does not create the registry (scratch tree after init: `\state`,
`\state\worker-settings.json`, nothing else).

### The numbers (attack E)

**`330 passed, 2 skipped` reproduces on BOTH interpreters over the lane's exact selection.** Not
piped:

```console
$ py -3.13 -m pytest tests/test_doc_claims.py tests/test_receipts.py tests/test_terminal_surface.py tests/test_lane_report_durability.py tests/test_views_doctrine.py -q -rs
330 passed, 2 skipped in 105.78s (0:01:45)

$ py -3.10 -m pytest <same selection> -q -rs
330 passed, 2 skipped in 88.04s (0:01:28)
```

**The 2 skips are the documented D4 pair and nothing is hiding in the count.** Identical reason on
both interpreters:

```console
SKIPPED [2] tests\test_views_doctrine.py:247: no view quarantines any more -- D4 is true of shipped
code, so an unqualified restatement is no longer a defect. This skip IS the green path;
`test_the_quarantine_detector_can_see_a_quarantine` keeps it from being reached by a broken detector.
```

They are the two parametrisations of
`test_doctrine_is_not_restated_unqualified_while_it_is_false` over `[CLAUDE.md]` and
`[terminal-surface.md]` (`tests/test_views_doctrine.py:235–250`) — exactly the pair root `CLAUDE.md`
describes, and its guard `test_the_quarantine_detector_can_see_a_quarantine` is among the 16 that
pass in that file. No third skip, no native-pin tier skipping inside the total.

**Extra, beyond the brief: the lane's 5-file selection was not hiding a break elsewhere.**

```console
$ py -3.13 -m pytest tests/ --ignore=tests/integration -q -rs
4139 passed, 5 skipped, 1 xfailed in 412.39s (0:06:52)
```

The other 3 skips are platform pins (symlink privilege, and the POSIX/Win32 partial-write sibling
pair), all self-describing.

### The fence (attack F)

**The repo fence held exactly.** Derived, with a positive control on a commit that does touch code:

```console
=== ALL PATHS TOUCHED BY 4ccc8f7 ===
M	README.md
M	docs/concepts.md
M	docs/getting-started.md
A	docs/lanes/w48-launch.md
M	docs/launch-readiness.md

=== FENCE PROBE: paths under bin/ tests/ docs/specs/ skills/ commands/ .claude-plugin/ ===
(above blank => none)

=== POSITIVE CONTROL for the same probe (a commit that DOES touch bin/) ===
bin/fleet.py
tests/test_core.py
```

`bin/fleet.py` is blob-identical at `fa236cb` and `4ccc8f7` (both `fc71106472f11d4a41cda7c7a7a6c9c4116067a6`),
so *"as of `fa236cb`"* is a legitimate pin rather than a stale one.

Live-machine fence claims: all verified — see MINOR-4 for the receipts and the one exception.

### The secondary claims (all MEASURED, all hold)

**33 subcommands, and the table really covers 33.** Derived from the shipped parser, counter
positive-controlled on a synthetic 3-item list:

```console
{home,knowledge,homes,init,spawn,status,peek,result,wait,send,interrupt,attach,release,respawn,resume-limited,kill,clean,archive,autoclean,index,q,doctor,sup-boot,sup-spawn,sup-checkpoint,sup-heartbeat,sup-release,sup-status,sup-context,sup-decision,sup-handoff-begin,sup-handoff-complete,sup-handoff-abort}
33
```

Then `comm` in both directions between the shipped set and the verbs the `getting-started` table
names, with `sup-handoff-{begin,complete,abort}` expanded:

```console
=== shipped-but-NOT-in-table (good answer: empty) ===
--- end ---
=== in-table-but-NOT-shipped (good answer: empty) ===
--- end ---
=== POSITIVE CONTROL: same comm with a planted missing verb ===
homes
```

`homes` is present in both tables (`README.md:154`, `docs/getting-started.md:273`).

**The `fleet knowledge` R2 loop — remedy runs, message byte-identical, exits 0.** Re-driven on a
gated scratch home:

```console
GATE PASSED -> C:/Users/Techn/.claude/jobs/ed03cd54/tmp/scratch2

=== R2 step 1 ===
knowledge rc=0
(no knowledge index at C:\Users\Techn\.claude\jobs\ed03cd54\tmp\scratch2\knowledge\INDEX.md -- run `fleet init`)

=== R2 step 2: run the remedy the message names ===
fleet init: wrote C:\Users\Techn\.claude\jobs\ed03cd54\tmp\scratch2\state\worker-settings.json
init rc=0

=== R2 step 3 ===
knowledge rc=0
(no knowledge index at C:\Users\Techn\.claude\jobs\ed03cd54\tmp\scratch2\knowledge\INDEX.md -- run `fleet init`)

byte-identical? True
=== scratch tree after init ===
\state
\state\worker-settings.json
```

Every element of the new `launch-readiness.md` paragraph holds: closed loop, rc=0 both times,
byte-identical message, and the remedy creates no `knowledge/`.

**`--max-budget-usd` advertised and always refused**, and the refusal is genuinely side-effect-free —
the guard is at `bin/fleet.py:6466`, the first `save_registry` in `cmd_spawn` at `6524`:

```console
$ fleet spawn probe --dir . --task "noop" --max-budget-usd 5
fleet: no USD budget under native dispatch (contract G3) -- use --token-ceiling
rc=1
state/fleet.json exists: False
```

**`fleet homes` read/write split, exactly as both new table rows describe:**

```console
$ fleet homes
fleet homes: C:\Users\Techn\.claude\fleet-homes.list
  (no homes listed -- this machine runs a single fleet)
rc=0

$ fleet homes --help
usage: fleet homes [-h] [--add PATH | --retire PATH]
  --add PATH     append <PATH> to ~/.claude/fleet-homes.list (must be an initialized fleet home)
  --retire PATH  append a retirement record for <PATH> (the home need not still exist)
```

**doctor is 28 checks, 28 PASS / 0 FAIL after init** — counted mechanically from the whole captured
output, never piped through `head`:

```console
[PASS] rows: 28
[FAIL] rows: 0        (rc=0)
```

**The four documented pre-init FAILs are exactly right**, and the total is preserved (24+4=28):

```console
rc=1
[PASS] rows: 24
[FAIL] rows: 4
[FAIL] worker-settings-instance: …\scratch2\state\worker-settings.json missing -- run `fleet init`
[FAIL] instance-freshness: worker-settings.json instance missing -- run `fleet init`
[FAIL] instance-grants: …\scratch2\state\worker-settings.json missing -- run `fleet init`
[FAIL] hook-registration: …\scratch2\state\worker-settings.json missing -- run `fleet init`
```

I also independently reproduced the lane's §11 INFO observation: on a brand-new home,
`claude-agents` reported **36** machine-global untracked sessions, `daemon-wedge` read
`daemon.lock held by pid 4188`, and `identity-witness` read this session's inherited `FLEET_WORKER`.
Their "doctor is not home-scoped" note is accurate.

**The Python floor and the pasted launcher failure.** `bin/fleet.cmd` really is
`py -3.13 "%~dp0fleet.py" %*` with no fallback and no `$FLEET_PYTHON`. The pasted text and exit code
are exact — and I checked the extrapolation the doc makes (*"On a box without 3.13…"*) by asking for
a **second** absent version, since 3.13 is installed here and could not be removed:

```console
$ py -3.12 bin/fleet.py --help          $ py -3.8 bin/fleet.py --help
No suitable Python runtime found        No suitable Python runtime found
Pass --list (-0) to see all detected …  Pass --list (-0) to see all detected …
or set environment variable PYLAUNCH…   or set environment variable PYLAUNCH…
or open the Microsoft Store to the r…   or open the Microsoft Store to the r…
true_rc=103                             true_rc=103
```

Byte-identical across two different missing versions, so the message is version-independent and the
generalisation is sound. `py -3.10 bin/fleet.py --help` → `usage: fleet [-h]`, rc=0.

**Links: 82 unbroken at the merge-base, 83 unbroken at the tip.** The lane counted at `fa236cb` and
then edited the docs; I re-checked the tree that would actually land, with anchor resolution, and
positive-controlled the checker on a seeded bad path *and* a seeded bad anchor before believing any
zero:

```console
=== POSITIVE CONTROL FIRST (must report exactly 2 seeded failures) ===
checked=85 broken=2
  README.md: MISSING PATH -> NO-SUCH-FILE.md
  README.md: MISSING ANCHOR -> docs/getting-started.md#no-such-heading

=== REAL RUN at 4ccc8f7 (the tree that would land) ===
checked=83 broken=0

=== SAME CHECKER at the merge-base fa236cb, for comparison ===
checked=82 broken=0
```

82 at the merge-base reproduces the lane's number exactly. The commit adds one link — `concepts.md`
→ `getting-started.md#become-the-manager` — and **its anchor resolves**, to `## Become the manager`
at `docs/getting-started.md:129`.

### Attack D — is anything missing that the rehearsal should have caught?

**§10's not-run list is honest and, for rehearsal *steps*, complete.** I walked the published
walkthrough against it: step 1 (clone + PATH) run, step 2 (`fleet home` + `init`) run, step 3
(plugin) not run **and listed**, step 4 (`--statusline`) not run **and listed**, step 5 (`doctor`)
run. `homes --add/--retire`, `doctor --repair`, any real `spawn`, and Linux/macOS are all listed. I
found **no quietly-skipped step** — the outcome the brief said would make the lane worthless did not
occur.

The one omission I did find is bookkeeping on the *gap* list, not the step list: MINOR-6.

---

## WHERE THE BRIEF WAS RIGHT AND WHERE IT WAS WRONG

The brief asked me to assume it contained an error. It named three candidates; **its first guess
landed.**

**1. "Finding 3 may matter more than finding 1" — LANDED, and more sharply than predicted.** The
brief guessed that if a fleet-launched lane cannot address a temp home by environment variable, then
every brief that fenced with `FLEET_HOME` fenced with nothing. That is true, and the corrected
guidance (`--fleet-home`, or the target clone's own shim) is *also* incomplete — MAJOR-1. The
clone's-own-shim primitive holds only while `~/.claude/fleet-homes.list` is absent, and nothing in
the lane report, this brief, or the new docs says so. It is absent today (verified before and after
every command I ran), which is the only reason my own fence and the lane's were sound.

**2. "The branch is docs-only and therefore low-risk" — the brief was right to distrust this**, and
all three MAJORs are the proof: every one is a prose defect that would ship with a fresh
measurement's authority attached.

**3. "Re-driving from a temp clone is unsafe" — did not land, under a stricter procedure than the
brief specified.** It was safe, but only because of a discipline the brief did not name: I ran
`fleet home` as a gate before *every* scratch-home command and aborted on mismatch, verified
`fleet-homes.list` absent immediately beforehand, and did the one genuinely risky measurement
(population scoping) as an **in-process pure-function call with `homes_list_path` monkeypatched** —
so the machine-wide list was never read, let alone written. Nothing needed to be left unreproduced.

---

## SUMMARY LEDGER

| # | Grade | Where | Finding | Evidence |
|---|---|---|---|---|
| 1 | **MAJOR** | `docs/getting-started.md:97` | Sid-lookup population is the machine-wide homes list ∪ install root, not install-root-scoped; the derived safety advice ("the target clone's own shim") is conditional and the condition is unstated | MEASURED — pure-function probe, 2 controls |
| 2 | **MAJOR** | `README.md:113`, `docs/getting-started.md:55`, `:82`, `docs/launch-readiness.md:80` | `# a DIRECTORY path, not a URL` contradicts `marketplace add --help` ("URL, path, or GitHub repo"); "no evidence either way" is false — 4 of 5 marketplaces in the quoted output are GitHub-sourced | MEASURED — `--help` + full `marketplace list` |
| 3 | **MAJOR** | `README.md:128`, `docs/getting-started.md:77` | "fix PATH" prescribed as the remedy; `FLEET_HOME` is a second cause the same doc documents 20 lines later | MEASURED — E3/E3b, PATH correct + env var set |
| 4 | MINOR | lane report §0 | Whole-`state/` "UNCHANGED each time" is not reproducible; 33 files written by other actors inside the lane's window. Conclusion independently true; receipt is not | MEASURED — mtime sweep of live `state/` |
| 5 | MINOR | `README.md:125`, `docs/getting-started.md:74` | Callouts justify step 2 with a hazard the new step 1 removes; instruction right, stated reason wrong | MEASURED — E1/E2, two temp clones |
| 6 | MINOR | `docs/launch-readiness.md:8` | Disposition sentence omits gaps 2b and 8 of 9; gap 8 unmentioned in the whole lane report | MEASURED — heading inventory + controlled grep |
| 7 | MINOR | `README.md:118`, `:133` | Two hunks with no measurement behind them: the `--statusline` warning (true, but code-read — §0 says it was never run) and a "One thing… Both" inconsistency | MEASURED — §0 quote + `bin/fleet.py:6084` |

**Cleared, each actually run:** claims 1, 2 and 3; `330 passed, 2 skipped` on 3.13 **and** 3.10 with
both skips named; full unit suite `4139 passed, 5 skipped, 1 xfailed`; the repo fence; the live
machine's `settings.json`, `fleet-homes.list`, statusline, plugin config and temp dirs; 33
subcommands and full table coverage; the R2 loop; `--max-budget-usd`; `--fleet-home` /
`not_initialized`; `fleet homes`; doctor 28/28 and the four pre-init FAILs; the Python floor and the
pasted launcher text; 82/83 links with anchors; and §10's completeness.

**I could not break:** the three headline claims. Each re-drove true from an independent clone, and
I tried to make each of them false.
