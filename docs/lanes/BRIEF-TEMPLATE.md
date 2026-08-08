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

## For a gate lane

A gate works in a detached worktree that never merges, so its verdict has no merge of its own to
ride. Order it onto **the branch under gate**:

```
**Deliverables:** your verdict committed at `docs/lanes/<gate-name>.md` **on the branch you are
gating** (`<branch>`), so it lands with that branch. If you reject the branch and it will not be
merged, commit the verdict to `main` instead — a rejection's reasons must outlive the branch.
```
