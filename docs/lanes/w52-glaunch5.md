# w52 gate 3 — `w52-glaunch5`: the narrow re-gate of the `w52-glaunch4` discharge

**Gate:** `w52-glaunch5`, worktree `C:/proga/fleet-w52-glaunch5`, branch `w52/glaunch5` @ `dc0e4f1`.
**Subject:** `305aeb6..dc0e4f1` — three commits, the lane's discharge of gate `w52-glaunch4`.
**Scope:** NARROW. I did not re-audit the launch axis. Gates 1 and 2 did that.
**Fix nothing:** nothing in this branch is repaired here. This file is the only file I add.

---

## VERDICT: **NOT-GATING** — 2 MAJOR, 4 MINOR

Recommendation: **land it, after two ten-minute edits.** The floors are green on both interpreters,
the merge is clean by measurement rather than by argument, `bin/` is untouched, and gate 2's strongest
artifact — the verbatim README peek block — is byte-identical to what gate 2 proved. Nothing found
here reverses a finding or changes what a reader does at a terminal.

But the class this gate was paid to sweep is **still open, and this discharge added to it.** Two of
the four items gate 2 grouped as *"restatements invalidated by my own later edits"* were repaired in
`68ecd44` **to values that `68ecd44` itself invalidated in the same commit.** The lane named the class
at `:1810-1814` and instantiated it 637 lines above, in the paragraph doing the naming's work.

| ID | Grade | Finding | Basis |
|---|---|---|---|
| **G1** | **MAJOR** | The m6 repair is wrong at the commit that made it, in **four** places, because that commit moved `README.md` by +5 lines | MEASURED |
| **G2** | **MAJOR** | `:1957` pastes a `git rev-parse` invocation that **exits 128** and cannot print the pasted output | MEASURED |
| **G3** | MINOR | M1's substituted instrument returns 0 **by construction** and is narrower than the question it is filed under | MEASURED |
| **G4** | MINOR | `docs/launch-readiness.md:109-112` still asserts a claim this branch refuted; the closure is recorded only in the exempt lane report | MEASURED |
| **G5** | MINOR | Six further stale `README line N` citations; the report runs **two incompatible citation standards at once** | MEASURED |
| **G6** | MINOR | §0 still asserts `main == 64b43c2`; the correction is 1,880 lines below with no marker at §0, against the report's own stated method | MEASURED |

**On the README self-contradiction the lane handed forward:** confirmed, and the judgement asked for
is in **§6** — *fix it before merge, in two files not one, and it still does not gate.*

---

## 0. Vantage — which tree every reading came from

I am standing on `w52/glaunch5` @ `dc0e4f1`. Wave 51 lost four measurements to conflating the tree an
instrument stands in with the tree it talks about, so every reading below names its tree.

```console
$ git rev-parse --abbrev-ref HEAD
w52/glaunch5
$ git rev-parse --short HEAD
dc0e4f1
$ git status --porcelain
(empty)
```

Four distinct trees are in play and they are **not** interchangeable:

| Tree | What it is | Used for |
|---|---|---|
| `dc0e4f1` | this checkout, the branch tip | README anchors, the floors, the doc population |
| `2517f6b` | materialised into a temp dir via `git archive \| tar -x` | the two M1 receipts, which pin themselves there |
| `64b43c2` | branch cut, and the report's declared vantage for source lines | the `bin/fleet.py` citations |
| `0d82460` | current `main`, which moved under the branch | the merge claims |

**`bin/fleet.py` is blob-identical at `64b43c2`, `main` and `HEAD`** (§7), so a source line number read
at any of them is a reading about all three. That is *not* true of `README.md`, and G1 and G5 are
entirely consequences of that asymmetry.

---

## 1. The cheap measurement first — `docs/launch-readiness.md` is not in the range

The brief said the lane's summary lists `docs/launch-readiness.md` among what this discharge changed,
and asked whether that is imprecision or a real error. **MEASURED at `dc0e4f1`:**

```console
$ git diff --stat 305aeb6 dc0e4f1
 README.md                |  15 +-
 docs/lanes/w52-launch.md | 366 ++++++++++++++++++++++++++++++++++++++++++-----
 2 files changed, 339 insertions(+), 42 deletions(-)

$ git log --oneline --follow -- docs/launch-readiness.md | head -1
2517f6b docs(w52): discharge the glaunch3 gate, and repair the two doc defects it confirmed
```

The brief's own claim is **correct**: the file is not in `305aeb6..dc0e4f1`; its last touch is
`2517f6b`, the first discharge.

**But I could not find the imprecise summary inside the deliverable.** The two places the committed
report enumerates its own changes are both exact:

- `:1886-1888` — *"**What this commit changes:** `docs/lanes/w52-launch.md`, `README.md` (both already
  modified on this branch), and nothing else."* **Correct** for `68ecd44`.
- `:1986-1987` — *"**this branch** touches only `README.md`, `docs/launch-readiness.md` and
  `docs/lanes/w52-launch.md`."* **Correct** for `64b43c2..dc0e4f1`, MEASURED:

```console
$ git diff --name-only 64b43c2 dc0e4f1
README.md
docs/lanes/w52-launch.md
docs/launch-readiness.md
```

So the artifact distinguishes *this commit* from *this branch* correctly in both places. If the lane's
turn-end result summary said otherwise, that text is outside the repo and I cannot read it. **Graded:
no defect in the deliverable.** See §8.

---

## 2. G1 — **MAJOR.** The m6 repair is stale in the commit that made it

**This is the finding the gate exists for**, and it is the named class reproducing inside its own
correction.

Gate 2's **m6** was *"'README line 136' is 164"*. The lane accepted it and, per its everywhere-rule,
applied `164` in **four** places in `68ecd44`. The same commit changed `README.md` with the hunk
`@@ -48,18 +48,23 @@` — **18 lines replaced by 23, a net +5, above every one of those anchors.**

**MEASURED — README anchor positions across the branch:**

| String | `64b43c2` | `2517f6b` | `305aeb6` | **`68ecd44` / `dc0e4f1`** |
|---|---|---|---|---|
| `Two things this quickstart cannot do for you` | 136 | 164 | 164 | **169** |
| `claude plugin marketplace add C:\path\to\this\clone` | 113 | 141 | 141 | **146** |
| `injected at the next tool boundary` | 81 | 109 | 109 | **114** |

```console
# tree: dc0e4f1
$ git show dc0e4f1:README.md | sed -n '141p;146p;164p;169p'
# 2. Check WHICH fleet you are about to configure, then render the hook wiring
claude plugin marketplace add C:\path\to\this\clone   # the directory form -- the one verified here
> prints something other than your new clone, check PATH **and** check `FLEET_HOME` before running
Two things this quickstart cannot do for you. The walkthrough is only executed as far as `fleet doctor`…
```

**The four sites, all wrong at `dc0e4f1` and all wrong at `68ecd44` — the commit that wrote them:**

1. `:1173` — *"MEASURED — **README line 164** reads"*. It is **169**. The parenthetical traces the
   history to `2517f6b` and **stops one commit short of the commit it is being written in.**
2. `:1204-1205` — a **pasted receipt**, not prose:
   ```
   :141  claude plugin marketplace add C:\path\to\this\clone   # the directory form -- the one verified here
   :164  …is the form a known-working install on the maintainer's machine reports, not a form
         re-executed on a clean box.
   ```
   **Neither anchor resolves.** At `68ecd44`, `:141` is a comment header and `:164` is a PATH warning.
   The correct anchors are `:146` and `:169`. This is a command-and-output-shaped claim that does not
   reproduce at its own commit — the same shape as **M1** and **G4** of the two prior gates.
3. `:1540` — the ledger INFO row: *"**README line 164** … README `:141` now **contradicts** `:164`"*.
4. `:1823` — the discharge table: *"**m6** — 'README line 136' is **164** — ACCEPTED — corrected in
   the body **and** in the ledger INFO row, which the everywhere-rule caught."*

**The everywhere-rule worked perfectly and propagated a wrong value to every site it reached.** That
is worth stating plainly, because the lane cites the everywhere-rule as the control that caught the
second instance. It caught the second *instance*; it cannot catch a wrong *value*, and nothing else
was watching.

**Why MAJOR and not MINOR.** Three reasons, and I considered MINOR seriously because the branch is
docs-only:

- It is a **receipt** at `:1204`, not a narrative aside. The repo's rule — root `CLAUDE.md` — is that
  a pasted command-and-output block is a claim until something re-runs it. Two gates have now graded
  exactly this shape MAJOR on this document (`G4`: 3 lines where a command prints 4; `M1`:
  `(no matches)` where a command prints 3).
- The citation is **load-bearing for the argument it appears in.** `:1204-1207` exists to prove README
  contradicts itself. A reader who opens the two cited lines sees a comment header and a PATH warning,
  and the contradiction is invisible. The argument cannot be checked from its own anchors.
- The lane **refused a lighter grade for its own defects** at `:1830-1832`: *"Arguing for a lighter
  grade here because the defect is mine would be the asymmetry this repo keeps paying for."* I am
  holding it to its own standard rather than inventing one.

**One thing the lane got right inside the wreckage, and it deserves saying:** `:1201` claims README
contradicts itself *"23 lines apart"*. **169 − 146 = 23. The relative claim survived the shift the
absolute anchors did not.** That is not luck — a distance between two lines in one file is invariant
under an insertion above both, and the lane happened to state the one form of the claim that could not
rot. It is the only citation in the group that is still true.

---

## 3. G2 — **MAJOR.** A pasted `git` receipt that exits 128

`dc0e4f1`, the newest commit on the branch, in the section headed *"`main` MOVED UNDER THIS BRANCH —
measured at close"*, `:1956-1959`:

```console
$ git rev-parse --short main origin/main
0d82460
0d82460
```

**MEASURED, live repo, `git version 2.34.1.windows.1`:**

```console
$ git rev-parse --short main origin/main
fatal: Needed a single revision
$ echo $?
128

$ git rev-parse --short=7 main origin/main
fatal: Needed a single revision

$ git rev-parse main origin/main
0d82460e1568ad8e6f608f42659063b43443c766
0d82460e1568ad8e6f608f42659063b43443c766
```

**`--short` puts `rev-parse` into single-revision mode.** Given two revisions it does not abbreviate
them — it refuses. Drop `--short` and it prints two revisions, at **full** 40-char length. There is no
invocation of `git rev-parse` that prints two seven-character shas on two lines. **The block is
composed, not captured.**

**The underlying fact is true.** `main` and `origin/main` both resolve to `0d82460`, MEASURED with
two single-revision calls. Nothing downstream of this receipt is wrong.

**Why MAJOR.** It is the same class as M1 and G4 on the same document, and the lane accepted the
grading precedent for it. Two aggravating facts and one mitigating one:

- **Aggravating:** it is in the *newest* commit, one commit after the lane accepted **m5**, whose
  entire disposition is *"caption now names both halves and instructs **capture-don't-compose**"*. The
  lane wrote that instruction into `README.md` and then composed a receipt.
- **Aggravating:** the section's stated purpose is *"I did not move it… I checked rather than assumed"*
  — a section about instrument discipline.
- **Mitigating, and I weigh it:** this defect is **self-announcing**. A reader who re-runs it gets
  `fatal:` and exit 128 immediately. M1's `(no matches)` was worse in kind — it returned a plausible
  false negative that concealed a live allegation. This one cannot mislead anybody who tests it.

**The rest of that section is clean, and this is the useful contrast.** The other three receipts in
the same fence group re-execute **byte-for-byte** — see §7. So the failure is not sloppiness across a
section; it is one block, and the one block is the only one that was retyped rather than pasted.

---

## 4. G3 — MINOR. The substituted instrument answers 0 by construction

The brief asked what it would take for `grep -n "still reads" docs/launch-readiness.md` to be
non-zero, and whether that condition can occur. **It can, barely — and the answer 0 is nonetheless the
repair restated rather than a check of it.**

**MEASURED — where the string went.** Using `-G`, not `-S`, per the brief's rule:

```console
$ git log --oneline -G'still reads' -- docs/launch-readiness.md
2517f6b docs(w52): discharge the glaunch3 gate, and repair the two doc defects it confirmed
b4de97a docs(w48): discharge the glaunch gate -- 3 MAJOR, 4 MINOR, and one gap that was false all along

$ git show 2517f6b -- docs/launch-readiness.md
-It was relayed from root `CLAUDE.md`, whose opening paragraph still reads *"M-D and M-E shipped
+It was relayed from root `CLAUDE.md`, whose opening paragraph then read *"M-D and M-E shipped
```

**The W52-6 repair is precisely the deletion of the only occurrence of the literal string.** So the
substitute returns 0 *because the repair happened*, not as independent evidence that it worked. To
make it non-zero, somebody would have to reintroduce that exact idiom into that one file. That is
reachable, so it has real value as a **narrow regression guard** — and none as the proof it is filed
under.

**Three ways it is narrower than the question above it.** The heading at `:1107` is *"The
everywhere-rule, applied and MEASURED after the fix"*, glossed as *"apply each repair everywhere the
claim appears, not where the gate quoted it"*:

| | The stated question | What the substitute asks |
|---|---|---|
| Scope | the whole tree | **one file** |
| Key | the claim | **one idiom** |
| Independence | evidence about the repair | **entailed by** the repair |

At `:1153` the lane calls it *"The command that answers the intended question"*. It answers a strictly
narrower one, and the narrowing is exactly where the third M1 hit (`w48-gc.md:479`) lived — a
whole-tree hit that a single-file grep can never see. The lane found that one by hand and disclosed
it; the substitute would not have.

**Positive control that the narrowing costs something real.** Ask the *semantic* question of the same
file and it is not clean — see **G4**.

**On the disclosure.** The lane's handling of the concealed allegation is **correct and I verified it
rather than accepting it.** `docs/lanes/w48-gc.md:479` charges `docs/launch-readiness.md` with saying
`29 checks`. MEASURED at `2517f6b` **and** at `dc0e4f1`, `docs/launch-readiness.md:290` reads:

```console
# tree: 2517f6b, materialised
$ sed -n '290p' docs/launch-readiness.md
- **`fleet doctor` earns its place.** 28 checks; on a fresh home it fails 4 with the exact remedy
```

`28`, not `29`. And `28` is right: **MEASURED at `dc0e4f1`, `cmd_doctor`'s `check_calls` has 28
entries**, derived by AST the way `_registered_doctor_checks()` does it. The lane's own grading of
this — *"luck, not diligence"* — is the correct one, stated without softening, and it is the best
paragraph in the discharge. **No finding here; recorded because a gate that only reports defects
mis-describes the document.**

---

## 5. G4 — MINOR. A stale repo-wide claim in a current-tree launch document

Reached by the everywhere-rule the brief told me to apply, not by re-auditing the launch axis.

`docs/launch-readiness.md:109-112`, at `dc0e4f1`:

> So the CLI plainly accepts URL and GitHub-repo sources, and four marketplaces on this box are
> installed that way. **What no one here has run is `claude plugin marketplace add` itself — in any
> form** — because it mutates this machine's real plugin configuration. The grade of the directory
> answer is therefore *observed source of a working install*, not *command re-executed on a clean box*.

**This branch refuted it.** `docs/lanes/w52-launch.md:240` — *"### Step 3 — the plugin. **RUN.** Wave
48 called this structurally unrunnable; it is not."* — with a positive control at `:265-278` proving
the operator's real config was untouched, then `:273` `add` rc=0, `:281` `list` showing
`Source: Directory (…)`, `:288` `install` rc=0.

The lane **knows**: *"`launch-readiness.md` gap 2a is **CLOSED** at the strongest grade available"*
(`:308`, again `:1464`, ledger row `:1538`). It recorded the closure **only in the lane report**,
which is the first entry in `_HISTORICAL_PREFIXES` and therefore exempt from every doc pin. The
current-tree document a stranger is sent to still says the opposite.

**Scoping discipline, applied against my own finding.** I nearly graded four sentences here and
withdrew three:

- `docs/launch-readiness.md:298` heads a section *"What this document did not verify"*, and the file
  self-pins in its header (*"Status: measured 2026-08-05 against `f457a57`"*, *"Re-measured 2026-08-09
  against `fa236cb`"*). The four `Not run` / `Not executed` bullets at `:300-317` are therefore
  **correctly scoped and NOT defects**, even though this branch ran three of the things they name.
  Grading them would have been the "fixing a pinned reference fabricates" error the brief warns about,
  and it is the error I was one instrument away from making.
- The disposition table at `:12-18` is dated and sourced to `docs/lanes/w48-launch.md`. **Pinned. Not
  a defect.**
- `:109-112` is different on every axis: it sits in the **body of live blocker 2a**, in a document
  titled *"what stops an external user today"*; it is phrased about the repo (*"no one here"*), not
  about the document; and it is the load-bearing sentence for the grade the entire entry turns on.

**MINOR, not MAJOR:** the branch's licence was narrow and repairing another document's blocker list is
plausibly outside it. What is *not* outside it is saying so in the current-tree file, or at minimum
recording in the report that the file now needs an edit. Neither happened.

---

## 6. The README self-contradiction — confirmed, and the judgement

**Confirmed, MEASURED at `dc0e4f1`:**

```console
:146  claude plugin marketplace add C:\path\to\this\clone   # the directory form -- the one verified here
:169  …And step 3's marketplace argument, a directory path to the clone, is the form a known-working
      install on the maintainer's machine reports, not a form re-executed on a clean box.
```

`:146` says verified here. `:169` says not re-executed on a clean box. This lane's §2 step 3 settles
it in `:146`'s favour. **The two disagree, 23 lines apart, on the launch-facing README.**

### The everywhere-rule applied to it — the answer is yes, and there is a fourth

| Where | Says | Consistent with §2? |
|---|---|---|
| `README.md:146` | *"the directory form -- the one verified here"* | ✔ |
| `README.md:169` | *"not a form re-executed on a clean box"* | ✘ |
| `docs/getting-started.md:55` | **byte-identical to README:146**, comment and all | ✔ |
| `docs/getting-started.md:84-89` | the disambiguating paragraph — *"the only form verified for this repo… what is untested is specifically whether `exPardus/fleet` resolves as a marketplace"* | ✔ |
| `docs/launch-readiness.md:70` | the general form, `<path-or-github-repo-of-this-clone>` | ✔ (neutral) |
| `docs/launch-readiness.md:109-112` | *"no one here has run… in any form"* | ✘ — **G4** |

So the claim is stated **five** times across **three** documents, and **two** of the five are false in
the same direction. The lane found one of them.

### The judgement, which is what was asked for

**Not acceptable to land as-is — and it does not gate the branch.** Four reasons, in the order that
decides it:

1. **It is not one edit, and the lane's estimate is wrong in the direction that makes deferral look
   cheap.** `:1213` says *"Whoever holds the settled grade should fix both ends in one edit. Still one
   paragraph of work."* MEASURED, the repair spans **two files**: `README.md:169` and
   `docs/launch-readiness.md:109-112` — because `README:169` *forwards the reader into*
   `launch-readiness.md` for exactly this claim (*"Both… are stated plainly in [Launch readiness]"*).
   Fixing README alone sends the reader to a document that repeats the false half.
2. **The correct text is already written and already gated.** `docs/getting-started.md:84-89` says the
   right thing, at the right length, in the right register, and it has been through a wave. The repair
   is nearer a copy than an authoring job. A deferral that costs a copy-paste is not a real deferral.
3. **The cost is credibility, and this is the document where credibility is the product.** README:169
   is *self-deprecating*, so it reads as scrupulous honesty rather than as an error. A stranger who
   reads `:146` and then `:169` does not conclude "one line is stale"; they conclude the maintainer
   does not know what they have verified. On the file whose whole job is a stranger's first ten
   minutes, that is the expensive kind of wrong.
4. **What keeps it off BLOCKING, and off GATING:** both readings hand the user the *same command with
   the same argument*. Nobody is misinstalled, nothing fails, no data is at risk. It is a credibility
   defect, not an operational one, and gating a green docs branch over it would be the asymmetry in
   the other direction.

**To the lander:** fix both ends before merge. Not as a condition of this gate — as the observation
that this is the third gate to touch this sentence, the branch will never be cheaper to fix than it is
right now, and the paragraph you need is sitting in `getting-started.md`.

---

## 7. What re-executed cleanly — the larger half of this gate

A gate that reports only defects mis-describes the artifact. Everything below is **MEASURED by me**,
and the tree is named on each.

### 7a. Both M1 receipts reproduce **exactly** at the commit they pin

Materialised with `git archive 2517f6b | tar -x -C <tmp>`, i.e. against the commit each receipt claims:

```console
# tree: 2517f6b, materialised
$ grep -rn "not yet folded into" --exclude-dir=.git .
./CLAUDE.md:5:…
./docs/lanes/w48-launch.md:831:…
./docs/lanes/w52-launch.md:1063:…
./docs/lanes/w52-launch.md:1075:…
./docs/lanes/w52-launch.md:1101:…
./docs/launch-readiness.md:260:…
./docs/launch-readiness.md:268:…
  hits = 7

$ grep -rn "still reads" --exclude-dir=.git . | grep launch-readiness
./docs/lanes/w48-gc.md:479:…
./docs/lanes/w52-launch.md:1109:…
./docs/lanes/w52-launch.md:1397:…
  match count = 3

$ grep -n "still reads" docs/launch-readiness.md ; echo $?
1
```

**Every path and every line number matches the pasted block.** The M1 repair is sound as a repair. Its
weakness is the substituted instrument (G3), not the re-execution.

**And the trap the brief warned about, which I nearly walked into.** Those five
`docs/lanes/w52-launch.md:1063/1075/1101/1109/1397` anchors are **all wrong at `dc0e4f1`** — the file
grew from 1,548 to 1,991 lines and `:1063` now reads *"The brief said `docs/launch-readiness.md`
inherited a known error…"*. **That is not a defect.** The block explicitly pins itself — *"both
commands re-executed against `2517f6b` materialised into a temp tree"* — so it is a claim about a past
tree and it stays true. Whose fault is the rot? **The format's, not the citation's:** `docs/lanes/`
is append-at-bottom, so any self-citation rots on the next append, and the only defence is the pin,
which this block has. Contrast **G1**, where the anchors carry no pin and are wrong at their own
commit — that one is the citation's fault.

### 7b. The `_roster_live_sids` census — 11 call sites, re-derived independently

Re-derived by AST at `dc0e4f1` (`bin/fleet.py` blob `3661d1f9…`, identical to `64b43c2`):

```
AST def sites          : [14869]
AST CALL sites (count) : 11
AST CALL sites (lines) : [8373, 8392, 8398, 9559, 9598, 9914, 10121, 15393, 15443, 15673, 18772]
bare Name refs (non-call): []
  _any_live                       x1  lines 9598
  _archive_eligible               x1  lines 10121
  _cmd_respawn_native             x3  lines 8373,8392,8398
  _cmd_respawn_supervisor         x1  lines 9559
  _doctor_check_supervisor_wedge  x1  lines 18772
  _render_boot_bundle             x1  lines 15393
  _wedged_release_gate            x1  lines 15673
  cmd_clean                       x1  lines 9914
  cmd_sup_boot                    x1  lines 15443
textual occurrences: 14 [8270, 8373, 8392, 8398, 9559, 9598, 9914, 10121, 14869, 15393, 15443, 15673, 18724, 18772]
```

**Byte-for-byte identical to `:655-671`**, including the by-function breakdown and the two docstring
lines (`8270`, `18724`) that account for the gate's surplus. The report's retraction of "13" is
correct.

### 7c. Every source-line citation resolves

MEASURED at `dc0e4f1`; the report pins these to `64b43c2` at `:70-71` and the blob is identical, so
they hold at both.

| Citation | Claimed | At `dc0e4f1` | |
|---|---|---|---|
| `bin/fleet.py:114` | `Path(__file__).resolve().parent.parent` | `INSTALL_ROOT = Path(__file__).resolve().parent.parent` | ✔ |
| `bin/fleet.py:3657` | `_NATIVE_STICKY` | `_NATIVE_STICKY = ("dead", "over_budget", …` | ✔ |
| `bin/fleet.py:7103`–`7138` | `_render_native_peek_lines` | `def` at 7103, `return lines` at 7138 | ✔ |
| `bin/fleet.py:8270`, `:18724` | two docstrings naming the helper | both are docstring prose | ✔ |
| `bin/fleet.py:8373` | `old_live = old_sid in _roster_live_sids(entries)` | verbatim | ✔ |
| `bin/fleet.py:14869` | the `def` | `def _roster_live_sids(entries: list) -> set:` | ✔ |
| `docs/getting-started.md:296` | *"all 33 subcommands"* | verbatim at `64b43c2` **and** `dc0e4f1` | ✔ |
| `docs/launch-readiness.md:222` | the struck §8 entry | verbatim at all three trees | ✔ |
| `docs/lanes/w48-gc.md:479` | the `29 checks` allegation | verbatim | ✔ |

### 7d. Four of the report's own greps, re-executed at `dc0e4f1`

`grep -n "user_settings_path()"` → the same four lines (`353`, `6040`, `6052`, `6204`), `grep -c` → 4.
`grep -n "Path.home()"` → the same ten lines, `grep -c` → 10, and the arithmetic behind *"four
path-returning helpers, one transcript read, five prose lines"* checks out. `grep -l "Path.home()"
bin/hooks/*.py bin/fleet_statusline.py` → no match, `ls bin/hooks/*.py | wc -l` → 4, so the null is
not vacuous. The status-literal extraction at `:744` returns the same ten statuses. **All reproduce.**

### 7e. `33 subcommands` and `28 checks` — and an instrument I got wrong first

`28` — `cmd_doctor`'s `check_calls` has 28 entries by AST at `dc0e4f1`. README `:154` and
`launch-readiness:290` are exact.

`33` — **my first instrument said 37 and it was wrong.** Counting raw `add_parser(...)` calls by AST
over the whole file picks up parsers that are not the top-level subcommand group and double-counts two
names. Counting the way the harness does — `build_parser()`'s `_SubParsersAction.choices`, which is
`_shipped_verbs()` at `tests/test_doc_claims.py:214-220` — gives **33**. The lane's *"33 subcommands,
matching `getting-started.md:296` — MATCH"* is correct. Recorded rather than quietly fixed, because it
is this gate's own instance of the brief's rule that an instrument answers about what it is actually
measuring, and mine was measuring the wrong population.

### 7f. Gate 2's verbatim README proof is still about the shipped bytes

The brief asked whether this discharge superseded the block gate 2 proved by replaying
`_read_tail_lines`, `_is_substantive_transcript_record` and `_render_native_peek_lines` over the
captured transcript. **It did not.**

```console
$ diff <(git show 305aeb6:README.md | sed -n '35,48p') <(git show dc0e4f1:README.md | sed -n '35,48p')
(no output)
```

`README:35-48` is **byte-identical** at gate 2's cut and at the branch tip. `68ecd44`'s hunk begins
below it and moves the `-- tokens` line inside the `fleet result` block. **Gate 2's proof stands
unre-run, and the anchors 35–48 are still the right ones** — the one README citation on the branch that
the +5 could not disturb, because the insertion is beneath it.

### 7g. The two README claims this discharge *added* are both true

`m4` and `m5` added factual prose to `README.md`. Verified at the source:

- *"`fleet result` prints the body to stdout and the `-- tokens` line to stderr"* — **MEASURED**,
  `bin/fleet.py:7247-7252`: `print(text)`, then
  `print(f"-- tokens in=…", file=sys.stderr)`. Body first, tokens second, tokens on stderr. The
  README's new order is the order the code emits, and the caption's mechanism (a pipe interleaves them
  differently) is right.
- *"`COST 0.00` … the native dispatch path never prints (it renders `-`)"* — consistent with the
  captured block at `README:31`, which shows `-`.

**m2, m3, m4, m5, m7 all discharged as the table claims.** m3's ledger row now reads *"named 2;
`over_ceiling` is a third"* (`:1581`) and `over_ceiling` is 12 characters, confirmed. m7's defence is
withdrawn in §8 with the traverse argument stated (`68ecd44` `+226-259`). **Only m6 is discharged to a
wrong value** — G1.

---

## 8. Floors — predicted before the run, then measured

**The prediction was written and journalled before any `pytest` invocation.** `--collect-only` and a
direct derivation of the doc population were used to fix clause 1 by construction, which the brief
permits.

### 8a. The prediction, and the derivation the brief asked for

**Does the README edit move the floor?** Derived from `tests/test_doc_claims.py` at `dc0e4f1`, before
running:

`README.md` is **not** exempt — `_HISTORICAL_PREFIXES` (`:445-469`) does not cover it, and it is in
both `ENTRY_DOCS` and `CHECK_COUNT_DOCS`. So four pins can see it, and the range's delta must be
checked against each:

| Pin | What it matches | The `305aeb6..dc0e4f1` README delta |
|---|---|---|
| `test_doctor_check_counts_match_the_registered_checks` | `<N> checks` | adds none |
| `test_doctor_pass_fail_tallies_sum_to_the_registered_checks` | `N PASS / M FAIL` | adds none |
| `test_fleet_verbs_written_as_commands_in_entry_docs_are_shipped` | `fleet <verb>` in backticks/fences | adds `fleet result`, `fleet peek`, `fleet status` — all shipped, all already in the file |
| `_PY_FLOOR` | `Python 3.x+` | adds none |

The `-- tokens` line **moved** within a fence but was not **altered**, so no token changed identity.
**Predicted: no floor movement, all pins PASS.** And the population cannot move either — the branch
adds exactly one `.md`, `docs/lanes/w52-launch.md`, and `"docs/lanes/"` is the **first** entry in
`_HISTORICAL_PREFIXES`; the other two files were already tracked, and modifying a file cannot change a
set of paths.

### 8b. Measured

Digest and both suites inside one command, on a committed and quiet tree, so no edit of mine could
land mid-window. The verdict file did not exist yet and is untracked in any case; the digest is over
`git ls-files`.

```console
=== TREE STATE ===
w52/glaunch5
dc0e4f1
porcelain:
(end porcelain)

=== DIGEST BEFORE ===
59a9c2f5c9b15d3fc98e41fb5a01d8f238f1bd13da12a9f72eb9f536666c8ee2  files=262

=== COLLECT-ONLY (3.13) ===
4636 tests collected in 8.05s

=== POPULATION (derived, not imported) ===
tracked .md       = 156
current_tree_docs = 30
```

```console
=== py -3.13 -m pytest -q ===
4621 passed, 14 skipped, 1 xfailed in 570.13s (0:09:30)

=== py -3.10 -m pytest -q ===
4621 passed, 14 skipped, 1 xfailed in 496.09s (0:08:16)

=== DIGEST AFTER ===
59a9c2f5c9b15d3fc98e41fb5a01d8f238f1bd13da12a9f72eb9f536666c8ee2  files=262
```

No `FAILED` and no `ERROR` line on either interpreter. **All four predicted clauses hold.**

| # | Predicted, before the run | Measured at `dc0e4f1` | |
|---|---|---|---|
| 1 | population 30, collection 4636, **by construction** | `current_tree_docs()` **30**, tracked `.md` **156**, **4636 tests collected** | OK |
| 2 | the README edit moves no pin — derived against all four pins that can see it | pass on both interpreters | OK |
| 3 | both interpreters GREEN at `4621 passed, 14 skipped, 1 xfailed` | exactly that, both | OK |
| 4 | digest pair matches, compared only against itself in this tree | **identical**, `files=` included | OK |

**These are the seventh and eighth full suite runs behind this branch** — the lane's six across three
commits, plus my two here, all `4621/14/1`. The reference floor at `64b43c2` is the same figure from
4,636 collected. **The 3.13 flake gate `w52-glaunch3` recorded did not appear in my 3.13 run either**,
which makes four independent 3.13 datapoints for the "flake" grade and none against it.

**Clause 3 was BELIEVED when written and is MEASURED now.** Clauses 1 and 2 were derived by
construction before the run and the run did not teach me anything about them — which is the point of
predicting.

**The digest is `59a9c2f5…`; the lane's clean pair is `f6987a04…`. Different, and I am not treating
that as a discrepancy** — the instrument is checkout-relative and answers *"did this run change
anything here?"*, never *"is this tree the same as that tree?"*. Mine is compared only against itself,
in this working tree. `files=262` matching the lane's `files=262` is a *separate* check (a tracked-file
count is not checkout-relative) and it agrees.

---

## 9. The merge — verified by the right instrument for each claim, and then measured directly

The lane makes three claims. The brief said to verify all three by blob id; **only one of them is a
blob-id question**, and I used the right instrument for each rather than the named one for all.

**Claim 1 — `main` moved by one journal-only commit.** A log-and-name question, not a blob question:

```console
$ git rev-parse main
0d82460e1568ad8e6f608f42659063b43443c766
$ git rev-parse origin/main
0d82460e1568ad8e6f608f42659063b43443c766
$ git log --oneline 64b43c2..main
0d82460 docs(w52): the wave's record, and the handoff before the expensive part
$ git diff --stat 64b43c2 main
 supervisor/JOURNAL.md | 1125 +++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 1125 insertions(+)
$ git merge-base --is-ancestor 64b43c2 main ; echo $?
0
```

**Reproduces exactly** — one commit, one file, 1,125 insertions, and `64b43c2` is an ancestor.
(The lane's own `git rev-parse --short main origin/main` receipt for the first two lines is **G2**;
the *fact* it asserts is confirmed here by two single-revision calls.)

**Claim 2 — `bin/fleet.py` is blob-identical at all three.** This one *is* a blob-id question, and
the lane chose the right instrument for the reason it gives: a blob id is computed after normalisation,
so CRLF cannot confound it the way a working-tree hash can.

```console
$ git rev-parse 64b43c2:bin/fleet.py main:bin/fleet.py HEAD:bin/fleet.py
3661d1f95bf4bb7adc3ee98fe5b311c04e89f352
3661d1f95bf4bb7adc3ee98fe5b311c04e89f352
3661d1f95bf4bb7adc3ee98fe5b311c04e89f352
```

**Identical.** Every source line number, AST derivation and code receipt in the report is a claim
about that blob, so all of them stand against current `main`. This is the load-bearing claim of the
whole section and it is sound.

**Claim 3 — no file overlap, so no conflict.** A set question, and then an empirical one. The lane
argued it; I measured it, and then measured the merge itself:

```console
$ comm -12 <(git diff --name-only 64b43c2 w52/glaunch5 | sort) <(git diff --name-only 64b43c2 main | sort)
(empty)

$ git merge-tree 64b43c2 main w52/glaunch5 ; echo $?
0
```

Read-only — the three-argument form writes no object and moves no ref. Entry statuses: `merged`
(`README.md`), `added in remote` (`docs/lanes/w52-launch.md`), `merged`
(`docs/launch-readiness.md`). **Zero `<<<<<<<`/`=======`/`>>>>>>>` markers, zero `changed in both`.**
The merge is clean by measurement, not by argument. **The lane's reasoning was right and now it is
also checked.**

### What a lander still owes — the brief asked for this and the lane's closing point is correct

The lane says *"The floor figures above were measured against this branch, not against a merge of it…
that is a prediction and nobody has run it."* **That is right and I am not repeating it, I am
sharpening it.** After merging, a lander owes:

1. **A post-merge floor on both interpreters.** My `4621/14/1` is about `dc0e4f1`, not about
   `merge(0d82460, dc0e4f1)`. The *prediction* is unchanged and I can strengthen its derivation:
   `supervisor/` is in `_HISTORICAL_PREFIXES`, so `supervisor/JOURNAL.md` is outside
   `current_tree_docs()` — population stays 30, collection stays 4636, and the +1,125 lines are
   invisible to every doc pin. **Derived. Not run. Still owed.**
2. **A re-check that `main` has not moved again.** Every number in §9 is about `0d82460`. `main` moved
   once under this branch already; the report's §0 is stale because of it (**G6**).
3. **A decision on G1, G2 and §6** — all three are cheaper before the merge than after, and none of
   them blocks it.
4. **Nothing about `bin/`.** The branch does not touch it, the blob is identical at three refs, and
   the suite is green twice.

---

## 10. G5 and G6, stated fully

### G5 — MINOR. Six further stale README citations, and two standards running at once

Beyond G1's four sites, the report carries six more `README line N` citations that do not resolve at
`dc0e4f1`. **None was written by this discharge**; all are inherited, and gates 1 and 2 did not catch
them either.

| Report line | Says | True at | At `dc0e4f1` |
|---|---|---|---|
| `:311` | *"README line 88"* — the no-injection row | `64b43c2` | **121** |
| `:962`, `:975`, `:1486`, `:1536` | *"README line 81"* — *"injected at the next tool boundary"* | `64b43c2`, `7c87730` | **114** |
| `:1034` | *"README's own line 49"* — the USD-budget prose | `64b43c2` | **82**; `:49` is **blank** |
| `:923` | *"README lines 28–33"* — the hand-written peek block | `64b43c2` | deleted by `2517f6b` |

**The real defect is not the six numbers; it is that the document runs two citation standards.**
`:70-71` pins **source** line numbers explicitly — *"Every source line number below was read in
`C:/proga/fleet-w52-launch/bin/fleet.py` at `64b43c2`; they are not transferable to another commit"* —
and pins **nothing** about README. Then the lane **accepted m6**, which is the ruling that a README
citation must be current at tip. Under the accepted standard, all six are stale. Under the alternative
standard — README citations pinned to the branch cut, like the source ones — m6 should have been
**refused** and `136` was right all along. **Both standards are live in the same file at the same
time, and that is what makes a sweep of this class unfalsifiable for the next gate.** One sentence in
§0 extending the source-line pin to README, or declining to, would close it permanently.

`:923` is the mildest of the six and I nearly withdrew it: it quotes the *pre-repair* README, so it is
inherently historical. It is listed only because it carries no marker saying so, and a reader who
opens `README:28-33` at the tip finds a `fleet status` block and no way to tell whether the report or
the README moved.

### G6 — MINOR. §0 still says `main == 64b43c2`

`:68`, unqualified and present-tense: *"Public HEAD == my branch base == `main` == the clone."*
`main` is `0d82460` and `origin/main` is `0d82460`, MEASURED in §9.

**The lane diagnosed this exactly** at `:1950-1952`: *"Recorded because a report whose §0 asserts
`main == 64b43c2` would otherwise ship a stale claim — the exact class of defect two gates have now
charged this document with."* It then wrote the correction at line **1948**, one thousand eight hundred
and eighty lines below the sentence, with **no marker at §0**.

That is against the report's own stated method at `:15`: *"Corrections are made **in place**, with
superseded text struck through or quoted rather than deleted."* Every other correction in the document
follows it; this one does not, and it is the one the lane identified itself.

**Whose fault — format or citation?** Both, and the split matters. The rolling append-at-bottom shape
of `docs/lanes/` guarantees that a late correction lands far from what it corrects; that is the
format's. But the lane *had the file open, named the defect, and had already struck text in place
elsewhere in the same commit*. Choosing append here is the citation's.

**Mitigation, stated because it is real:** `:6` date-pins every MEASURED line to 2026-08-09, so the
receipt at `:54-55` is a dated reading rather than a standing claim. And the **inference** §0 exists to
license — that readings taken in the clone are readings about this repo — survives intact, because
`bin/fleet.py` is blob-identical at all three refs (§9). **The reader is misled about `main`, and about
nothing the report concludes.** That is what keeps it MINOR.

---

## 11. Sweep coverage — what I actually resolved, and the sampling rate

The brief predicted the 1991-line sweep might be intractable and told me to report a sampling rate if
I truncated. **I did not truncate.** It was tractable because I extracted the citation population
mechanically rather than reading linearly.

| Population | Size | Resolved | Method |
|---|---|---|---|
| `file:line` citation strings | 22 | **22 / 22** | regex extraction, each resolved against a named tree |
| `README line N` / `README:N` / `lines N–M` | 9 distinct | **9 / 9** | anchor tracked across all 7 branch commits |
| internal `§N` cross-references | 13 distinct targets | **13 / 13** | all resolve to headings (§0–§12, §1a–§1d) |
| pasted `$ ` command lines | 60 | **17 re-executed**, 43 classified | see below |
| numeric claims with units | 37 distinct | **19 re-derived**, 18 classified unverifiable | see below |
| doc-population / floor numbers | 5 | **5 / 5** | `--collect-only` + direct derivation |

**The 43 unre-executed commands** are `fleet`/`claude` invocations against a throwaway home that no
longer exists, plus statusline/JSON captures. They are **volatile by nature** — evidence outside the
repo — and re-running them would require re-driving the rehearsal, which is the *lane's* job and not a
narrow gate's. **Named, not silently skipped.**

**The 18 unverified numerics** are wall-clock timings (`0.26 s`, `9:30`, `74s`, …), narrative counts of
the lane's or the gate's own actions (`6 drives`, `13 runs`, `three 3.13 runs`), and one capture-derived
byte count (`25 characters`). None is re-derivable from the tree at any commit. **Named, not silently
skipped.**

**Result of the sweep: seven defects in the citation population** — G1's four sites and G5's six
citations, spanning eight report lines — **and zero in the source-citation, numeric, or receipt
populations except G2.** The class the lane named is confined almost entirely to `README.md` anchors,
and the reason is structural: `README.md` is the one cited file the branch **edits**, and the report
pins its `bin/fleet.py` citations but not its `README.md` ones.

### On `tools/verify_receipts.py`

The brief said to run it over any spec file this branch touched, and to say whether the branch's
receipts are inside its population at all.

**They are not, and the count is zero.** MEASURED at `dc0e4f1`:

```console
$ git diff --name-only 64b43c2 dc0e4f1 | grep -c '^docs/specs/'
0
```

The branch touches `README.md`, `docs/launch-readiness.md` and `docs/lanes/w52-launch.md`. The
harness's population is `SPEC_DIR.glob("*.md")` (`tests/test_receipts.py:172`), i.e.
`docs/specs/*.md`. **There is nothing to run it over.** The lane's statement at `:1812-1814` —
*"Nothing in this repo's harness re-checks an in-document citation; `tools/verify_receipts.py` would,
but it enforces `docs/specs/**` only"* — is **MEASURED-correct**, and it is the accurate diagnosis of
why G1 and G5 exist. This is the third gate to charge this document with a citation defect and the
first to be able to say the gap is structural rather than attentional: **three lanes with three
different authors, all warned, all careful, have now put a wrong in-document citation into this file.
That is an argument for extending a harness, not for grading a fourth author harder.**

---

## 12. Every `fleet` command I ran, and which home it touched

**NONE. Zero `fleet` verbs, in any home.**

The brief predicted this and told me not to invoke `fleet home` to "gate" myself, since that call
would be my only exposure rather than a fence. **I did not.** The subject of this gate is three
docs-only commits; nothing in grading them requires the CLI.

- **`fleet` CLI invocations: 0.** No `home`, no `doctor`, no `status`, no `init`, nothing.
- **`FLEET_HOME`: never set, never read by me.**
- **`~/.claude`: never written.** No `settings.json`, no `fleet-homes.list`, no
  `fleet-statusline-chain.json`. No `fleet init` against any home.
- **One thing that must be disclosed rather than assumed away:** I ran
  `import fleet; fleet.build_parser()` **in-process** once, to count subcommands the way
  `_shipped_verbs()` does (§7e). That is a module import, not a CLI invocation — it constructs an
  `argparse` object and exits. It takes no lock, reads no registry, resolves no home beyond the
  module-level `INSTALL_ROOT = Path(__file__).resolve().parent.parent`, which is **this worktree**.
  The full test suite does the same import 4,636 times per run. Recorded because "I ran no fleet
  commands" would be true-but-incomplete, and incompleteness in a containment statement is the thing
  this repo keeps paying for.
- Scratch files: `$CLAUDE_JOB_DIR/tmp` only (the materialised `2517f6b`, the floor script and its
  output, the `merge-tree` output). Nothing outside it, nothing in the live home.
- **Refs: none moved.** One commit to `w52/glaunch5`, which is this gate's deliverable. No push, no
  merge, no branch created or deleted. `git merge-tree` in §9 is the three-argument read-only form; it
  writes no object and moves no ref.

---

## 13. WHERE THIS BRIEF WAS WRONG

The brief invited refusals and noted that seven of seven refusals this wave were right. I have four
corrections and one refusal.

**1. "The subject lane ran zero `fleet` verbs and you probably can too." — WRONG about the lane, right
about me.** The lane ran **dozens**. `docs/lanes/w52-launch.md:1254-1277` is a section titled *"Every
`fleet` command I ran, and which home it touched"*, with a three-fence table covering `home` ×10,
`init`, `init --statusline` ×3, `doctor`, `spawn`, `status` ×13, `peek` ×4, `send` ×4, `wait` ×3,
`result`, `respawn` ×4, `interrupt`, `resume-limited`, `kill`, `clean` — plus one deliberate,
disclosed invocation of the **live** shim. The claim is true only of the three commits in
`305aeb6..dc0e4f1`, which are docs-only. As written it would tell a successor gate that §7 is empty,
and §7 is one of the report's more careful sections. **The conclusion drawn from it was still right:**
I ran zero.

**2. "The lane's own summary lists [`docs/launch-readiness.md`] among what this discharge changed" —
not locatable in the deliverable.** Both places the committed report enumerates its changes are exact,
and they correctly distinguish *this commit* from *this branch* (§1). If the lane's turn-end summary
said this, it is not in the repo and no gate can grade it. **The brief's suggested first measurement
was still worth doing** — it fixed the range in five seconds and every later reading depended on it.

**3. "Verify all three by blob id — CRLF cannot confound a blob id, which is why it chose that
instrument." — right about one claim, over-generalised to three.** Only claim 2 (`bin/fleet.py`
identity) is a blob-id question. Claim 1 is a log-and-diffstat question and claim 3 is a set question,
and a blob id answers neither. I used the right instrument for each and added `git merge-tree` for
claim 3, which upgrades it from argument to measurement (§9). **The CRLF reasoning is correct where it
applies**, and it is the reason claim 2 is the section's load-bearing one.

**4. "Likeliest wrong: that M1's substituted instrument is sound" — the brief was right to doubt it,
and the mechanism is worse than 'merely returns 0 for a different reason'.** It returns 0 because the
repair *deleted the string it searches for* (§4). The brief's framing — *"an instrument chosen after
the fact to produce the answer the author wants"* — describes it precisely.

**5. "Do not re-audit the launch axis" vs "apply the everywhere-rule … is the marketplace form stated a
third time anywhere in the tree?" — these pull against each other, and I resolved it toward the
explicit instruction.** Answering the everywhere-rule question honestly required reading
`docs/getting-started.md` and `docs/launch-readiness.md`, which is launch-axis territory. **G4 came
out of that** and it is a real finding in a current-tree document. I did not widen further: I did not
re-check the statusline, the fence, the worker lifecycle, or anything gate 1 or gate 2 graded. **If
the manager meant the everywhere-rule to stop at `README.md`, then G4 is out of scope and should be
handed to whoever owns `docs/launch-readiness.md` — but it is true either way, and I would rather be
told I over-read the fence than have it sit for a fourth wave.**

**6. Where the brief was RIGHT and it mattered most:** *"A pinned receipt is a claim about a PAST tree
and stays true. Before grading any citation stale, ask whether the citing document pins itself."* I had
five `docs/lanes/w52-launch.md:NNNN` anchors inside the M1 receipt queued as a finding before I checked
the pin, and four `Not run` bullets in `docs/launch-readiness.md` queued before I read its header and
its section title. **All nine would have been fabrications.** That is nine of the fifteen candidate
findings this gate started with, killed by one rule the brief paid for in advance.

---

## 14. Findings ledger

| ID | Grade | Where | Basis | Introduced by this discharge? |
|---|---|---|---|---|
| **G1** | **MAJOR** | `w52-launch.md:1173`, `:1204-1205`, `:1540`, `:1823` | MEASURED | **YES** — `68ecd44` |
| **G2** | **MAJOR** | `w52-launch.md:1956-1959` | MEASURED | **YES** — `dc0e4f1` |
| **G3** | MINOR | `w52-launch.md:1151-1159` | MEASURED | **YES** — `68ecd44` |
| **G4** | MINOR | `docs/launch-readiness.md:109-112` | MEASURED | No — pre-existing, refuted at `7c87730`, undisclosed since |
| **G5** | MINOR | `w52-launch.md:311`, `:923`, `:962`, `:975`, `:1034`, `:1486`, `:1536` | MEASURED | No — inherited; missed by gates 1 and 2 |
| **G6** | MINOR | `w52-launch.md:68` vs `:1948` | MEASURED | **YES** — `dc0e4f1` recorded it and did not correct in place |
| — | INFO | README `:146` vs `:169`, plus `launch-readiness:109-112` | MEASURED | No — disclosed by the lane; **judgement in §6**: fix in **two** files before merge |
| — | INFO | `verify_receipts.py` cannot see any file this branch touches (0 spec files) | MEASURED | No — structural; the argument for a harness change is in §11 |

**Nothing found reverses a finding. Nothing found touches `bin/`. Nothing found changes what an
operator types.**

**Landing recommendation: land it.** Fix §6 in both files and G1's four anchors first — together they
are under twenty minutes and they are the difference between a launch-facing README that contradicts
itself and one that does not. G2, G3, G5 and G6 are report hygiene in a `docs/lanes/` file that is
dated history by the repo's own exemption logic; fix them if the lane gets another turn, and do not
hold the branch for them.
