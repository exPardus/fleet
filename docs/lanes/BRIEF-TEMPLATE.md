# Lane brief — deliverables stanza

Paste this into a lane brief (`state/tasks/lens/<name>.md`) and fill the angle brackets. It exists
because the deliverables line was hand-written fresh every wave, and 55 of the briefs on this
machine ordered the report to a **relative** `state/journals/<name>.md` — resolved against the
lane's own worktree, which is disposable. Three reports were lost that way in one campaign; see
`docs/lanes/README.md`.

## The stanza

```
**Lane:** <build|gate|research>. Worktree `<path>`, branch `<branch>` at `<sha>`. Mode <mode>.
**Fence:** commit to your branch only. No push, no merge to `main`, no other ref moved.
**Deliverables:** your branch, and your report **committed on that branch** at
`docs/lanes/<name>.md` — MEASURED/BELIEVED per line, with a WHERE THIS BRIEF WAS WRONG section.
Your branch will get an adversarial gate — write for that reader.
**Journal** (working state, not the report) at `<fleet home>/state/journals/<name>.md`.
```

## The two lines that matter, and why

**The report path is `docs/lanes/<name>.md` and it is committed.** Not `state/journals/`. The
report rides the merge that lands the work, so durability costs the lane nothing it was not
already doing. A report left in any `state/` is in no commit and dies with the worktree.

**The journal is named separately and is allowed to be disposable.** It is working state for the
lane's own next session after a respawn or a compaction. Naming both, with the distinction stated,
is what stops the next brief from collapsing them back into one path — that collapse is the
measured defect, not the journal itself.

## The safety stanza — `FLEET_HOME` IS NOT A FENCE

Paste this into any brief whose lane will run `fleet` verbs and must not touch the live home.

```
**Safety:** for a home that is ALREADY INITIALISED, pass `--fleet-home <temp>` EXPLICITLY on every
`fleet` invocation meant for it. For a home you are about to CREATE, the flag cannot be used (see
below) — set `FLEET_HOME` and **remove `CLAUDE_CODE_SESSION_ID` from the child environment**;
that removal, not the env var, is what makes the fence hold. EITHER WAY, gate the whole run on
`fleet home` invoked exactly the same way: if it does not print your temp path, run nothing else.
Compare it NORMALISED — `fleet home` prints `as_posix()`, so a literal string compare against a
Windows path fails on the separators and looks like a breach that is not one. Point `INSTALL_ROOT`
at a throwaway worktree too, so a step-4 install-root fallback cannot reach the real home. Never
`fleet init` against the live home; never append to `~/.claude/fleet-homes.list` (RATIFIED
DESTRUCTIVE, only the fold reverses it); never write `~/.claude/settings.json`. Enumerate every
`fleet` command you ran and which home it actually touched, in your report.
```

**Why the env var does not work on its own, measured 2026-08-09 (wave 48), three runs, one
discriminator:**

| run | `FLEET_HOME` | sid | `fleet home` answers |
|---|---|---|---|
| baseline | unset | present | the live home |
| env set | temp dir | present | **the live home — the env var is IGNORED** |
| env set | temp dir | **removed** | the temp dir — the env var works |

A lane is a fleet-launched session, so its sid resolves to the live home through multi-fleet §5
step 2, and **step 2 outranks step 3 (validated env)**. This is the ratified resolution order
behaving exactly as specified — the code is right and the *briefing doctrine* was wrong, which is
the more dangerous shape, because nothing tests a brief. A supervisor fenced a live lane with
`FLEET_HOME` this wave and had to steer it mid-flight.

**And `--fleet-home` cannot name a home you are about to `init`.** Added 2026-08-09 after two
lanes measured it independently — gate `w48-gc` §6, and again on `w48/hookargv` while discharging
that gate. The first version of this stanza said *"pass `--fleet-home <temp>` explicitly on every
invocation"* without qualification, which is unusable for the one case it matters most in: the
`init` + `doctor` drive that every lane touching home resolution ends up running.

```
fleet home --fleet-home <fresh temp dir>
  rc=1
  fleet: --fleet-home <dir> is not initialized (not_initialized) -- an initialized home is one
  whose `state/fleet.json` exists and parses (docs/specs/multi-fleet.md, Definitions). Nothing
  was created.
```

§5 step 1 validates that `state/fleet.json` exists and parses. A fresh temp dir has no such file —
and, measured in the same drive, **`fleet init` does not create one either**, so the flag never
becomes usable on that home by initialising it. That is why the stanza above splits the two cases
instead of naming one idiom: the flag for homes that already exist, the env-plus-sid-removal for
homes that do not, and `fleet home` as the gate in both.

**Do not read a clean containment audit as proof the fence worked.** Ask a lane to explain *why* it
was contained, not merely to assert that it was.

**And the reason this file gave for that rule was itself wrong — corrected 2026-08-09 (wave 51).**
It said wave 48's audit came back clean because `~/.claude/fleet-homes.list` did not exist, *"so the
lookup population was empty and the live home was never a candidate."* **The population is never
empty.** Measured by lane `w51-initprep` and confirmed in the shipped code:

```
# at 7b2ff75
grep -n "list(listed\[.members.\]) + \[legacy\]" bin/fleet.py
  4621:    for ident in list(listed["members"]) + [legacy]:
```

`resolution_population()` appends the legacy install-root home **unconditionally** — §8's completion
is what removes that term, and §8 is an open operator decision. With an absent list the population is
still `['C:/proga/claude-fleet']`, and the lane drove the discriminator both ways: **sid present +
list absent → the live home; sid removed → the temp path.** So the fence fails today for every
fleet-launched lane, list or no list.

**The remedy above is unchanged and still correct.** Only the reason was false — and a false reason
in a doctrine file is worse than none, because this stanza's entire purpose is teaching a lane to ask
*why*, and it pointed at the wrong why. Note also what this is: **a correction of a correction.** The
wave-48 paragraph was itself a fix, and it shipped a wrong mechanism attached to a correct
measurement — the shape wave 50 found four times. Assume this paragraph has one too.

## For a gate lane

**Ask whether the repair was applied EVERYWHERE the repaired claim appears** — not whether it is
correct where it was applied. A discharge that fixes a finding at the site the gate quoted, and
leaves the same claim standing elsewhere in the same file, passes every question a gate normally
asks. Measured 2026-08-09 by gate `w51-glaunch2` against the launch-blocker discharge: a retracted
census number still shipped **328 lines below the paragraph retracting it**, and a file named EXEMPT
at two sites was moved into the held population by a third site **in the same commit**. Both had been
"discharged"; both greps take one second. **That gate's five questions were all answered soundly and
its largest finding was in a sixth nobody asked.** For every claim a discharge retracts or restates,
grep the whole tree for the *old* claim before grading it — not the changed lines, not the diff, the
tree. A repair verified only where it was applied is a repair verified nowhere.

A gate works in a detached worktree that never merges, so its verdict has no merge of its own to
ride. Order it onto **the branch under gate**:

```
**Deliverables:** your verdict committed at `docs/lanes/<gate-name>.md` **on the branch you are
gating** (`<branch>`), so it lands with that branch. If you reject the branch and it will not be
merged, commit the verdict to `main` instead — a rejection's reasons must outlive the branch.
```

## Proving a run changed nothing — NOT with `git write-tree`

Every brief in this campaign carried the instruction *"prove the tree sha is identical before and
after each run"*, and every lane that followed it with `git write-tree` **inherited a vacuous
check**. Measured independently by lane `w50-d` and its gate `w50-gd` on 2026-08-09: `git write-tree`
hashes the **index**, not the working tree, so with unstaged changes it returns `HEAD^{tree}`
unchanged and the before/after comparison **cannot fail** — which is every lane's normal state
during a test run. It answered the same sha across 900 lines of edits. It is also blind to untracked
files entirely.

Use a working-tree digest instead. Print it immediately before the floor run and immediately after;
the two lines must match, **`files=` included** — that count is not decoration, it is what catches a
skip rule that silently swallowed the tree.

```python
#!/usr/bin/env python3
"""A digest of the WORKING TREE, not the index. Print before and after a run and
compare; identical means the run modified nothing."""
import hashlib, sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
SKIP = {".git", "state", "logs", "mailbox", "__pycache__",
        ".pytest_cache", ".ruff_cache", ".fleet-index"}

h, n = hashlib.sha256(), 0
for p in sorted(ROOT.rglob("*")):
    if any(part in SKIP for part in p.relative_to(ROOT).parts) or not p.is_file():
        continue
    h.update(p.relative_to(ROOT).as_posix().encode("utf-8"))
    h.update(hashlib.sha256(p.read_bytes()).digest())
    n += 1
print(f"{h.hexdigest()}  files={n}  root={ROOT}")
```

`state/`, `logs/` and `mailbox/` are gitignored runtime planes a run may legitimately touch, and the
cache directories churn by design; everything else — **including untracked files, which
`git write-tree` cannot see at all** — is in.

**It is CHECKOUT-RELATIVE. Compare it only against itself, in one working tree.** It hashes bytes on
disk, and checkout applies line-ending normalisation (`core.autocrlf`, `.gitattributes`), so **two
clean worktrees of the same commit can produce different digests at an identical `files=` count.**
Measured by gate `w50-gd2` on 2026-08-09 against two checkouts of `5a47819`, both `files=242`. That
is not a defect in the instrument — a byte digest is supposed to see bytes — but it means the digest
answers *"did this run change anything here?"* and never *"is this tree the same as that tree?"* For
the second question use `git rev-parse HEAD^{tree}` on committed trees, or compare `git status`
plus the commit sha. **This caveat shipped one commit late: the amendment above landed without it,
which is the same class of defect the amendment itself documents — an instrument published without
the census of what it does not cover.**

This does **not** replace `tests/conftest.py`'s session-scoped
`_the_real_install_plane_is_byte_identical_afterwards`, which hashes the git-tracked code plane
*inside* the run and is strictly better for that plane, because it fails the suite rather than a
human's eye. The digest above covers what that fixture does not.

## Three rules for the instruments themselves — planters, probes and pins

*Added 2026-08-09 (wave 51), each measured by a lane against its own tooling.*

**A mutant planter must work on BYTES.** Lane `w51-slicee` restored a mutant in text mode and got
back a **byte-different CRLF file while printing a matching sha256** — the digest agreed and the
tree had changed. Read and write `rb`/`wb`, and compare bytes.

**A probe must not sit on the surface it is repairing.** The same lane's first probe went **silent
after the fix**, which reads exactly like "fixed". A probe that the repair can disable measures
nothing; put it somewhere the repair cannot reach, and seed it to prove it still fires.

**A pin whose failing path performs the act it forbids damages the machine every time it goes RED.**
The same lane's canary fixture wrote the homes list *before* proving the path was sandboxed —
contained only by a `USERPROFILE` fence, and caught by a guard added in the same commit. Order the
sandbox proof **above** the act, always.

**And byte-identity of a cited line is the load-bearing check for a re-pin, not name containment.**
Lane `w51-livemerge` seeded this: **AST name-containment accepts a re-pin target five lines wrong.**
The same lane found the deeper trap — `tests/test_self_citations.py` resolves line numbers in
`bin/fleet.py` **about itself only**, so a merge touching no `bin/fleet.py` citations makes it green
*correctly* while 108 cross-document citations rot behind it. **Name the oracle's population before
you trust its colour**; a supervisor ordered that pin run to fixpoint as a merge's re-pin oracle and
would have shipped all 108 green.

## Anchor the conflict-marker grep, or it counts prose

`grep -c '<<<<<<<'` over merge output counts any line that merely *contains* the marker, including
documents that quote it. Measured 2026-08-09 by lane `w50-mp` and reproduced at the wave-50 landing:
the campaign's long-quoted control value for `w35/nd4c × main` was **26**, and the true count is
**25** — the extra hit is a context line in `knowledge/INDEX.md`, the wave-42 lesson *about* the
marker-grep null, quoting the marker in its own prose. **The lesson was corrupting the instrument it
exists to protect, and an unanchored grep cannot tell.**

Use the anchored form, which `docs/NEXT-SESSION.md` already had right:

```
grep -cE '^\+?<<<<<<<'
```

The rule that produced the control in the first place still stands and is unaffected: **run any
measurement whose good answer is 0 against a known non-zero input first.** This amendment is about
making the non-zero input's number trustworthy too.

**A control value is a receipt, so PIN IT — and the `25` above did not, when it shipped.** *(Added
2026-08-09, wave 51.)* The paragraph above stated 25 without naming the commit it was measured at,
while **the value is a function of `main`, which moves every wave.** That is a receipt with no pin —
the same defect this file diagnoses two paragraphs earlier, and precisely what CLAUDE.md's receipt
rule exists to prevent. Caught by gate `w51-glaunch2`, against the supervisor that quoted the bare
number in four briefs the same day.

It is not academic: two measurements of *the same named pair* on 2026-08-09 disagree. The supervisor
measured, and enumerated all 25 hits as genuine `+<<<<<<< .our` lines —

```
# at 7b2ff75
git merge-tree $(git merge-base main w35/nd4c) main w35/nd4c | grep -cE '^\+?<<<<<<<'
  25
```

— while gate `w51-glaunch2`, same day and same declared pair, reports **anchored 26 / unanchored 31**
with five prose markers across three files. Neither reconciled the two, which means **they did not
run the same measurement.** That is the lesson, not the digit. **Quote the command, the commit, and
the number together, or quote none of them** — and use whatever your own run produces at your own
base, writing down which. Both 25 and 26 discharge the duty the control exists for, which is to be
non-vacuous.
