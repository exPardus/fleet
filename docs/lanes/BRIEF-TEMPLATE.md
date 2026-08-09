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

**Do not read a clean containment audit as proof the fence worked.** Wave 48's audit came back
clean for the wrong reason: `~/.claude/fleet-homes.list` did not exist, so the lookup population
was empty and the live home was never a candidate — while the lane's own sid *was* in the live
registry. One `fleet homes --add` and that protection is gone. Ask a lane to explain *why* it was
contained, not merely to assert that it was.

## For a gate lane

A gate works in a detached worktree that never merges, so its verdict has no merge of its own to
ride. Order it onto **the branch under gate**:

```
**Deliverables:** your verdict committed at `docs/lanes/<gate-name>.md` **on the branch you are
gating** (`<branch>`), so it lands with that branch. If you reject the branch and it will not be
merged, commit the verdict to `main` instead — a rejection's reasons must outlive the branch.
```
