# w47-durable — lane reports durable BY CONSTRUCTION

**Lane:** build. Worktree `C:/proga/fleet-w47-durable`, branch `w47/durable` off `main` at
`5a320f1`. 2026-08-09.
**Status:** COMPLETE. Floors green on both interpreters, predicted exactly. No fenced file touched.

This report is the first customer of its own fix: it is committed on this branch at the tracked
path the design specifies, and only mirrored into `state/journals/`.

---

## 1. The retro-sweep — ordered first, and it came first

**Result: one rescue, one already-durable, and otherwise clean.**

Method, MEASURED. `git worktree list --porcelain` from the main repo enumerated **62** worktrees.
`find <wt>/state -type f` over all 61 non-main worktrees — not just `journals/` and `verdicts/`,
the whole of `state/`, so nothing filed elsewhere could hide. Then a second, wider sweep over all
**83** directories under `C:/proga/` to catch a worktree that had been removed from git's list but
whose files were still on disk. Both sweeps agree.

Every file found in any non-main worktree's `state/`, in full — the list is this short:

| File | Verdict |
|---|---|
| `C:/proga/fleet-w41-rc/state/journals/w41-rc.md` (20,739 B) | **RESCUED.** Existed nowhere else. |
| `C:/proga/fleet-w45-ga2/state/verdicts/w45-ga2.md` (38,815 B) | Already duplicated; byte-identical (md5 `b9c0751…`) to `C:/proga/claude-fleet/state/verdicts/w45-ga2.md`. |

Two other worktrees (`fleet-hs-rs`, `fleet-w46-a3`) have an **empty** `state/` directory. Every
other worktree has no `state/` at all.

**The rescue.** `w41-rc.md` is the report of branch `w41/rc-constant` (`1191833`) — the
`verify_receipts.py` INCONCLUSIVE-vs-FAILED tri-state lane. It was the only copy: absent from the
fleet home's own `state/journals/`, and `git log --all` finds no commit that ever added a file of
that name or containing its text. It is now committed at `docs/lanes/w41-rc.md` with a `RESCUED`
provenance header; the body below the header is byte-identical to the original (md5 `fec1173…`
both before and after). The header says explicitly that its presence does **not** claim the branch
merged — as of the rescue, it had not.

**What was already durable.** The a2 gate verdict (brief's instance 3) — because a wave-46
supervisor hand-copied it. That is the mechanism this lane exists to replace, and it worked
exactly once, by luck.

**A clean sweep is a result, so plainly: beyond the three known instances I found nothing else.**
That is a smaller haul than the brief expected, and the reason is worth recording rather than
celebrating — most lanes' reports are not sitting in worktrees waiting to be rescued because
**they are already gone**. `state/` dies with the worktree and nothing keeps a copy; a sweep can
only find what has not yet been destroyed. The two known-lost reports (w44-ceil, slice a3) are
unrecoverable and this sweep did not recover them.

---

## 2. Re-deriving instance 1, as ordered — and one thing has changed since the brief

The brief asked me to re-derive the lost `w44-ceil` §8 GOALS text before building on it. Four
checks, three confirm the brief exactly and one no longer does:

1. **No `w44-ceil` file in `state/journals/`.** CONFIRMED. The directory now holds 58 files (the
   brief said 56 — two lanes have reported since); none is named `w44-ceil`.
2. **The lane's worktree has no `state/` at all.** CONFIRMED — `C:/proga/fleet-w44-ceil` (HEAD
   `cc65dab`) has no `state/` directory.
3. **The pointer is real and was relayed four times.** CONFIRMED — `supervisor/JOURNAL.md:6200`
   (*"exact text in state/journals/w44-ceil.md §8"*), `:6230`, `:6306`, and the gate verdict
   `state/verdicts/w45-gceil.md:598`.
4. **`git log --all -S"Context band (350"` returns EMPTY.** **NO LONGER TRUE, and the substance is
   unaffected.** It now returns exactly one commit: `ee62ecd`, *"docs(gates): open the
   lost-GOALS-text gate"* — which is three commits below my own base. The string appears there
   only inside the docket entry that **records the loss**, because that entry quotes the search
   command as part of its evidence. **The search for the lost text now finds only its own
   obituary.** Anyone re-deriving this in future gets a hit and must read it before concluding the
   text survived. I have written that trap into `docs/lanes/README.md` so the next person does not
   fall into it.

Instance 2 re-derived while I was there, and it is slightly worse than the brief states.
`logs/archive/w46-a3/` contains exactly one file, `w46-a3.jsonl` — no `.md`. `cmd_archive` moves
`state/journals/<name>.md` into `logs/archive/<name>/` when it archives, so the absence of a `.md`
means **there was no journal at the fleet home to move**: the lane had written to its own
worktree's `state/`, which is now empty. Archiving did not destroy the report; it was already
gone. (And `logs/` is gitignored too, so archival was never durability either.)

---

## 3. The design, and the alternatives I rejected

### What shipped

**A lane's report is committed on the lane's own branch at `docs/lanes/<lane-name>.md`, and
arrives on `main` with the merge that lands the lane's work.**

- `docs/lanes/README.md` — the convention, the measured defect record, the rejected alternatives,
  and a machine-readable declaration `<!-- lane-report-root: docs/lanes -->` that the pin reads.
- `docs/lanes/BRIEF-TEMPLATE.md` — the deliverables stanza a supervisor pastes into a lane brief,
  with a separate stanza for gate lanes.
- `skills/fleet/SKILL.md` and `skills/fleet/supervisor.md` — the instructing surfaces.
- `tests/test_lane_report_durability.py` — the pin (§5).

### The journal/report split, which is the actual conceptual fix

The defect is a **conflation**, not a bad directory. Two different artifacts were sharing one path:

| | **Journal** | **Report** |
|---|---|---|
| Path | `$(fleet home)/state/journals/<name>.md` | `docs/lanes/<name>.md`, on the lane's branch |
| Audience | the lane's own next session after respawn/compaction | the adversarial gate, and every later reader |
| Lifetime | scratch; `fleet clean` deletes it, `fleet archive` moves it | permanent, arrives on `main` with the merge |
| Durable? | **no, and that is correct** | **yes, by construction** |

Keeping the journal disposable is deliberate and load-bearing, and it answers the strongest
objection to the branch-commit shape (§7.2b): a lane that dies *before* it writes its report leaves
a partial journal at the fleet home, which survives the worktree. The journal is the
crash-survivable partial record; the report is the durable final artifact. Making journals durable
too would commit every compaction landmark to git.

### Rejected: copy-on-death

One more thing that can be forgotten, and it **cannot run when the death is the machine losing
power** — this fleet was dead 2.7 days this week for exactly that. A durability scheme that
requires the dying process to act is not a durability scheme.

### Rejected: "just always write the absolute `$FLEET_HOME/state/journals/` path"

This is the fix someone will propose, it is a genuine improvement, and it is **not enough** — see
§7.1, where I show the machine-generated preamble already does this and reports still died. It
converts *dies with the worktree* into *dies with the machine*, which is the failure this fleet
actually suffered. The path is still gitignored, still deleted irreversibly by `fleet clean`, still
in no commit and no backup. My pin sees through the disguise deliberately: `_normalise()` strips
`$FLEET_HOME/`, `$(fleet home)/` and `<fleet home>/` prefixes before asking git, so the absolute
spelling is graded exactly as disposable as the relative one.

### Rejected: `knowledge/`

Git-tracked, so it would be durable. But `knowledge/` holds *distilled* lessons that the learning
loop curates and that `knowledge/INDEX.md` keeps readable; lane reports are raw primary evidence,
one per lane, thousands of lines each. A lane's *lesson* still belongs in `knowledge/lessons.md`.

### Rejected: commit reports straight to `main`, or to an orphan `reports` branch

Straight-to-`main` violates the standing lane fence (*"commit to your branch only, no other ref
moved"*) and serialises every lane on one ref. An orphan branch is new mechanism requiring a branch
switch mid-lane. Both fail the test the preferred shape passes: durability should cost the lane
**nothing it was not already doing**.

### The one case the shape does not cover cleanly, disclosed

**A gate works in a detached worktree that is never merged, so its verdict has no merge of its own
to ride.** The brief did not raise this and it is a real gap in the "artifact of the branch"
argument. Ruling, documented in both README and the template: a gate lands its verdict at
`docs/lanes/<gate-name>.md` **on the branch it is gating**, so the work and the verdict on it
arrive together; if it rejects the branch and the branch will not be merged, it commits the verdict
to `main` instead, because a rejection's reasons must outlive the branch. **The pin does not
enforce this** — it is convention only, and I say so rather than implying coverage.

---

## 4. The diff

Base `5a320f1`. Seven files, +1238/−1.

```
 docs/lanes/BRIEF-TEMPLATE.md         |  40 ++++
 docs/lanes/README.md                 | 103 ++++++++++
 docs/lanes/w41-rc.md                 | 350 ++++++++++++++++++++++++++++++++   (the rescue)
 docs/lanes/w47-durable.md            | 372 +++++++++++++++++++++++++++++++++++  (this report)
 skills/fleet/SKILL.md                |   3 +-
 skills/fleet/supervisor.md           |  16 ++
 tests/test_lane_report_durability.py | 355 +++++++++++++++++++++++++++++++++
 7 files changed, 1238 insertions(+), 1 deletion(-)
```

`bin/fleet.py`, `docs/specs/multi-fleet.md`, `tests/test_home_resolution.py`,
`tests/test_verb_effect_guard.py`, `tests/test_round7_defect_pins.py` and
`tests/test_terminal_surface.py` are all UNTOUCHED. Nothing under `docs/specs/**` was touched, so
no `# at <sha>` receipt obligation arises.

---

## 5. The pin, and the plants that prove it reddens

`tests/test_lane_report_durability.py`, 15 tests, new file.

**Disposability is asked of git, not hardcoded.** Every verdict about whether a path is disposable
comes from `git check-ignore` against the repo's live ignore rules. The file carries no list of
bad paths. Add `reports/` to `.gitignore` tomorrow and a surface pointing reports there goes RED
without a line of the test changing — that is the property; a literal-string allowlist would only
ever have been a spelling.

**What it can and cannot assert, stated in the file.** It cannot check that a future lane obeyed
the convention; no test can. It checks that the durable location is real and tracked, that the
premise (`state/` is ignored) still holds, and that the surfaces which instruct lanes do not point
a report at a disposable path.

### The three plants

Each was planted, watched RED, then restored and the pin re-confirmed GREEN before the next.

**Plant 1 — the silent revert.** Deleted the new report bullet from `skills/fleet/SKILL.md` and
put back the original one-line journal bullet: exactly what a quiet return to the old convention
looks like, leaving **no offending string for a scanner to find**.
→ RED: `test_every_surface_names_the_declared_report_root[skills/fleet/SKILL.md]` —
*"skills/fleet/SKILL.md never names the declared lane-report root 'docs/lanes'."*
This is the seed that makes the whole class non-vacuous.

**Plant 2 — the historical defect, verbatim.** Appended the shape from
`state/tasks/lens/w44-ceil.md:5` to `supervisor.md`:
`- Deliverables: your branch, report `state/journals/<name>.md` MEASURED/BELIEVED…`
→ RED: `test_no_surface_points_a_report_at_a_disposable_path[skills/fleet/supervisor.md]` —
*"ignored: ['state/journals/<name>.md']"*.

**Plant 3 — re-point the declaration.** Changed README's declaration to
`<!-- lane-report-root: state/journals -->`.
→ RED on **three** tests at once: `test_the_declared_root_is_not_disposable`
(*"is GITIGNORED, so a report committed there would not be committed at all"*),
`test_the_declared_root_is_tracked_by_git`, and the SKILL.md instruction test.

### A fourth reddening I did not plant, and it is the most useful one

On its **first** run the pin failed four tests while the repo was entirely correct. Two of those
were the detector seeds, and they were right to fail: `subprocess` text mode translates `\n` to
`os.linesep` on Windows, so git received `state/journals/x.md\r`, matched nothing, and answered
"nothing is ignored". **A detector that had silently stopped discriminating would have made every
durability verdict in this file green and worthless.**
`test_the_detector_can_tell_a_disposable_path_from_a_durable_one` caught it on the first run, from
a bug I wrote myself and was not looking for. Fixed by feeding NUL-delimited **bytes**
(`check-ignore --stdin -z`), which also removes git's c-quoting of odd paths.

The other two first-run failures were **false positives in my own rule**, and fixing them made the
pin sharper. Block-wide word matching fired on the `fleet archive` and `fleet doctor` rows of
SKILL.md's command table and on supervisor.md's boot-bundle paragraph — passages that correctly
name a gitignored runtime path and separately use "report**s**" as a *verb* about what a command
prints. Rather than allowlist them (an allowlist is how a pin stops being evidence), the rule now
requires a report word within 120 characters **before** the path token, which distinguishes *"the
verb reports"* from *"your report goes here"*.

---

## 6. Floors — predicted, then measured

Base re-derived at my own branch point (`5a320f1`), clean tree, both interpreters, **before** any
edit landed on disk. Delta derived by `--collect-only` on the new file, never by counting
`def test_` lines.

| | py 3.13 | py 3.10 |
|---|---|---|
| **Base, measured** | 4037 passed / 14 skipped / 1 xfailed, **4052** collected, rc=0 | identical |
| `--collect-only` delta | **+15** | **+15** |
| **Predicted** | 4052 / 14 / 1 of **4067**, rc=0 | same |
| **Measured** | **4052 passed / 14 skipped / 1 xfailed of 4067, rc=0** | **4052 passed / 14 skipped / 1 xfailed of 4067, rc=0** |

Predicted exactly, on both, including the prediction that no existing test changes outcome.

**No floor run was started with a mutant on disk.** Every plant was reverted with
`git checkout -- <file>` and verified: SKILL.md and supervisor.md restored to their exact
pre-plant md5s (`c362934c…`, `bebbc0af…`); README.md restored to content byte-identical to its
staged blob (md5 `da2bfac9…` both from `git show :docs/lanes/README.md` and from the worktree file
with CRs stripped) — the raw on-disk bytes differ from pre-plant **only** in line terminators,
because `git checkout` re-materialised an LF file as CRLF under this repo's autocrlf, which is what
any clone gets. `git diff` against the index is empty, and `grep -rn 'lane-report-root: state'`
finds nothing. The floors above were run after that verification.

---

## 7. WHERE THIS BRIEF WAS WRONG

### 7.1 The stated mechanism is right about the outcome and wrong about the proximate cause — and the difference matters

The brief says: *"`state/` is gitignored, and a git worktree gets its own `state/`. So a lane that
writes its report to `state/journals/<name>.md` writes it into a directory that dies with the
worktree."*

Both sentences are true. The inference between them is not automatic, and **the machine-generated
preamble is the counter-example**. `bin/fleet.py:1566–1571` (`_PREAMBLE_TEMPLATE`) renders
`{journal_target}` from `journals_dir()`, which is `FLEET_HOME/state/journals` — an **absolute**
path at the main repo, not the worktree. My own brief carries it:
`C:/proga/claude-fleet/state/journals/w47-durable.md`. A lane obeying the preamble does **not**
write into its worktree.

The reports died because the **hand-authored deliverables line in the lens brief names a relative
path**. `state/tasks/lens/w44-ceil.md:5` reads:

> `Deliverables: your branch, report `state/journals/w44-ceil.md` MEASURED/BELIEVED per line…`

Relative, so it resolves against the lane's cwd, which is the worktree. **Measured across all
briefs on this machine: 55 order the relative form, 84 the absolute.** Both spellings are on the
same file for different reasons and at different speeds.

**Why this correction is load-bearing rather than pedantic:** the natural repair for the mechanism
as the brief states it is *"make every brief use the absolute path"* — and someone will propose
it, because it is cheap and it does fix the worktree half. It would leave every report gitignored,
deletable by `fleet clean`, in no commit and no backup. The defect is not *which* `state/`; it is
`state/` at all. I made the pin normalise `$FLEET_HOME/`-prefixed paths precisely so that this
half-fix cannot pass it.

### 7.2 "Committing-to-the-branch is the best shape" — attacked, and it survives, with two disclosed holes

Attacked as ordered. It holds, and I did not choose differently. The three real objections:

**(a) A rejected branch.** A report on a branch that is never merged does not reach `main`. It is
still *in git* and reachable while the ref exists — categorically better than `state/` — but if the
ref is deleted the commit becomes unreachable and eventually gc'd. **Mitigation shipped:** a gate
that rejects a branch commits its verdict to `main` directly. **Residual risk accepted and stated:
deleting a lane's branch destroys its report.** Nothing in this lane prevents that, and if the
interface wants that closed it is a separate piece of work (§9).

**(b) A lane that dies before it writes its report.** Real, and the brief's shape alone does not
cover it — a report written once, at the end, is written after the crash that kills the lane. This
is the strongest objection and it is why **I kept the journal disposable at the fleet home rather
than folding it into the report**: `$FLEET_HOME/state/journals/<name>.md` survives the worktree, so
the partial record survives an early death even though it is not durable long-term. Two artifacts
with two lifetimes, deliberately. A design that moved journals onto the branch too would have made
this worse, not better.

**(c) Gate verdicts have no merge to ride.** §3, disclosed. The brief's "artifact of the branch"
argument is clean for build lanes and needs the extra ruling for gates.

### 7.3 "My read is that it does not [require a `bin/fleet.py` change]" — correct as stated, incomplete as guidance

**I did not take the file, and I did not need to.** Durability comes from the branch commit;
enforcement comes from the pin over the instructing surfaces. The brief's read is correct.

But the brief invited me to attack it, so: **the single highest-coverage instructing surface in
this system is inside `bin/fleet.py`.** `_PREAMBLE_TEMPLATE` is the only instruction that reaches
**every** lane unconditionally, machine-rendered, with no supervisor in the loop. What I shipped
reaches supervisors who read `skills/fleet/*.md` and brief-writers who paste the template — which
is where the defect actually entered, so it is the right target — but a lane briefed by a
supervisor who skipped the skill is still uninstructed about its report.

**This is a finding, not a blocker, and it does not change my verdict on the fence.** The
recommended follow-up is one line added to `_PREAMBLE_TEMPLATE` naming the report path beside the
journal path, so every lane is told both, and `bin/fleet.py` then joins `SURFACES` in my pin. I
have left a note saying exactly that in the test file's `SURFACES` docstring. **I recommend it be
done by whoever holds `bin/fleet.py` next, not by re-opening the fence this wave** — the brief's
instinct that two lanes in one file is worse than a one-wave delay is right.

### 7.4 Smaller corrections

- **"There are ~30 worktrees"** — there are **62** (`git worktree list`), and 83 directories under
  `C:/proga/`. I swept all of both. The brief's expectation that most would have nothing was
  correct and then some: only **two** non-main worktrees held any report file at all.
- **"`state/journals/` holds 56 files"** — now **58**.
- **"`git log --all -S"Context band (350"` returns EMPTY"** — now returns `ee62ecd`, three commits
  below my base. §2.4. Substance unchanged; the check is now self-poisoned and needs a note, which
  I wrote into README.
- **"a copy-on-death scheme… cannot run when the death is the machine losing power"** — endorsed
  and re-used. No correction; recording that I checked it rather than assumed it.

---

## 8. Findings for the interface

1. **`_PREAMBLE_TEMPLATE` should name the report path** (§7.3). One line in `bin/fleet.py`, held
   by `w47-a3fix` this wave. Highest-leverage remaining coverage gap.
2. **Two reports are unrecoverable**: `w44-ceil` §8 (the GOALS replacement text an operator ruling
   is blocked on) and slice a3's self-report. This lane could not and did not recover them. The
   open gate in `docs/OPERATOR-GATES.md` still needs its ruling, and a supervisor-drafted
   reconstruction remains the only executable path.
3. **55 existing briefs under `state/tasks/` still order the relative path.** They are gitignored
   and historical, so I left them alone; but any of them re-used as a template re-introduces the
   defect. The template at `docs/lanes/BRIEF-TEMPLATE.md` exists to be copied *instead*.
4. **Deleting a lane's branch still destroys its report** (§7.2a). Accepted this wave, stated so it
   is a decision rather than an oversight.
5. **`logs/` is gitignored too**, so `fleet archive` moving a journal to `logs/archive/<name>/` is
   not durability either — worth knowing before anyone proposes archival as the fix.

---

## 9. Result summary

**Changed:** `docs/lanes/{README,BRIEF-TEMPLATE,w41-rc,w47-durable}.md` (new), `skills/fleet/SKILL.md`,
`skills/fleet/supervisor.md`, `tests/test_lane_report_durability.py` (new pin, 15 tests).
**Verified:** floors 4052 passed / 14 skipped / 1 xfailed of 4067, rc=0, **identical on py3.13 and
py3.10**, predicted exactly; three plants each watched RED and restored, restoration proved by md5
and by an empty `git diff`; one unplanned detector reddening caught a real bug in the pin itself.
**Blocked:** nothing. Two known-lost reports remain unrecoverable, which is a fact about the past,
not a blocker on this branch.
