## 2026-09-10T10:36:53Z CHECKPOINT inc=inc-20260910T075355Z-4f99 sid=42445477-de98-4813-937a-e18c965de740

WAVE 62 PUSHED (`1aae852..64aa96b`, 14 commits, `rev-list --count HEAD --not --remotes` = 0) AND
WAVE 63 DISPATCHED — two disjoint lanes. Floor triple-measured; one measurement-hygiene error of my
own, recorded against myself.

## THE FLOOR, AND WHY THERE ARE THREE RUNS INSTEAD OF TWO

**Predicted 4978 / `6 failed, 4955 passed, 16 skipped, 1 xfailed` in writing before running, derived
from `_HISTORICAL_PREFIXES` rather than guessed. HIT EXACTLY, THREE TIMES:**

| tree | interpreter | result |
|---|---|---|
| `afa51a8` | 3.12 | `6 failed, 4955 passed, 16 skipped, 1 xfailed` — 356.25s |
| `ea22902` | 3.10 | same — 417.62s |
| `ea22902` | 3.10 (re-run) | same — 382.61s |

Same six host-assumption ids every run, no new failures, no `skipif`.

**The third run exists because I made the error this repo already has a lesson about.** I checked on
a 3.10 run, found an empty output file and no `pytest` process, and concluded the harness had killed
it for memory — the harness has killed watchers three times, so the story fit. **It was alive:
`uv` was still building the interpreter environment, a phase that has neither a `pytest` process nor
output.** I then chained a SECOND 3.10 run into the same clone, so two suites overlapped in one
tree — exactly what `#2026-09-09-w55-server-first-wave` forbids (*"a lane whose deliverable is a
measurement runs alone or in its own worktree"*), committed by the supervisor, while landing a wave
whose entire value is measured receipts.

**I did not wave it through on the grounds that the number looked right.** The overlapping run
returned the exact predicted figure with the identical six ids, which is strong evidence — but
"probably uncontaminated" is not a receipt, so I let the third run (which had the tree to itself for
most of its life) settle it. **It agreed to the digit, so the overlap is demonstrably harmless
rather than presumed so**, and that is the only reason the push went out.

**The lesson is upstream of the numbers, and it is this wave's shape for the third time today:
ABSENCE OF A PROCESS IS NOT ABSENCE OF A JOB.** I read "no row in `pgrep`" as death, exactly as the
keeper reads "no row in the roster" as death and as `_investigate_no_outcome` reads "no outcome" as
death. **Three detectors, one error, and I hand-executed it myself while writing the brief that
fixes the other two.**

## WAVE 63 — TWO LANES, DELIBERATELY DISJOINT

1. **`w63-sidunion`** (branch `w63/sid-union`, from `64aa96b`) — the fork-sid join. The claim row
   becomes *"the roster row of ANY sid in the claim-holder's registry sid union"*, then
   `status == "busy"`; and the interface profile's two-live-body guard takes the same join. Pinned
   against **both** of today's events: the 10:16Z false page must not fire, and yesterday's true
   stall must still page at `21:04:36Z` — using `w62-keeperc`'s corrected **7h09m59s**, not the
   7h10m51s the gate and its evidence base both quote.
   **The brief names `sup-status --json` publishing the union as a FIRST-CLASS option**, not an
   afterthought: it may be the cheapest correct fix and it keeps the keeper narrow under D4. I told
   the lane the deliverable is a sound join, not the site I guessed.
2. **`w63-statusline`** (branch `w63/statusline-home`, from `64aa96b`) — G-K5 item (1) ONLY.

**Item (2) of G-K5 is HELD and the brief says why in those words.** *"`fleet init` inside a repo
creates a home there"* creates a home, which appends to `~/.claude/fleet-homes.list` — **the exact
act G-K7 is asking the operator to rule on.** Building it now would perform, as a routine step, the
thing under gate. The ruling's own escape clause (*"if either collides with §5 or with the E2
destructive tier for `init --home`, FILE A GATE, do not build around it"*) is satisfied by G-K7
already standing; nothing further is owed but the wait.

**G-K1 is NOT dispatched, on purpose.** It is keeper work and `w63-sidunion` owns
`bin/fleet_keeper.py` this wave. Two lanes in one file is how a wave loses a receipt. It goes next.

## THE CORRECTION I CARRIED INTO THE STATUSLINE BRIEF
My own dogfood brief told a lane the per-home statusline was UNBUILT. **Half wrong, measured by
`w62-dogfood`: per-home RESOLUTION is built and working (two homes, two different rows); what is
unbuilt is the row CARRYING THE HOME'S IDENTITY.** A lane briefed on my version would have rebuilt
the existing half. The new brief leads with the correction AND tells the lane to re-derive it
against the real surface, because I am handing on a fact I did not measure myself.

Also corrected in me by that lane and now recorded so it stops propagating: I claimed
`fleet.json.corrupt.*` at `:982` was **the only** state-path glob. **There are nine.** The
conclusion (no sibling sweep, `fleet-dogfood` is a safe name) survives — but I offered that sentence
AS the confirmation, and confirming it falsifies it. I had already repeated the false version in a
checkpoint.

## PROCESS CHANGE APPLIED, NOT MERELY FILED (standing goal 4)
`docs/lanes/BRIEF-TEMPLATE.md` amended at `9f79bee` with the two dogfood findings that generalise:
**`env -u CLAUDE_CODE_SESSION_ID` is required on EVERY cross-home invocation including
`--fleet-home` and including ORDINARY READ VERBS** (the §5 step 1 guard refuses `fleet home` itself,
and its remedy advises dropping the flag — walking the lane back into the live home); and **the
`fleet home` gate is unsatisfiable for the one call that creates a home**, sound for every call
after it. **55 briefs on this machine inherited the first defect, mine included.** Fixed in the
template rather than in one report, which is where the last five waves' process changes died.

## STATE
`64aa96b` pushed, tree clean, three w62 worktrees still present + two new w63 ones. Two lanes
working, three w62 lanes idle and archivable next beat. RAM 4.0 GB available, 15 `bg-spare`.
Context ~205k — BELOW-BAND against 350k. **G-K7 OPEN and untickable by me or any lane; the dogfood
append stays HELD pending both the ruling and an interface restart** (the profile is read at
interface startup, so landing the edit protects a future interface, not the one that would revive
me). Watcher armed on both lanes — **and it is still the mitigation that a fork defeats**, which is
what `w63-sidunion` exists to make unnecessary.

## 2026-09-10T11:22:16Z CHECKPOINT inc=inc-20260910T075355Z-4f99 sid=42445477-de98-4813-937a-e18c965de740

WAVE 63 — ITEM 1 IS DONE ON THE OPERATOR'S OWN CRITERION. Standing directive 2026-09-10 adopted:
priority order fixed, meta-work capped, gate reflex capped, this checkpoint is short by rule.

## SHIPPED
- `1de9995` merge `w63/statusline-home` — nameplate carries a per-home tag; single-home row is
  byte-identical (the pre-existing suite is the non-regression pin).
- `2b0ad5a` profile(G-K7 A) — interface profile names `--fleet-home` on `autoclean` + 3 `sup-spawn`.
- `aee5fdf` **THE APPEND IS MADE.** `fleet homes --add /home/altai/proga/fleet-dogfood`.

**G-K7 DISCHARGED BY DOING, NOT BY RULING** — the directive names it by example. Box left unticked
(operator's alone) with a dated note saying no ruling is owed.

## MEASURED AFTER THE APPEND, ON THIS HOST
```
bare unmembered `fleet autoclean`   -> rc=1  "this machine runs 2 fleets ... name the home"
same call WITH --fleet-home         -> archived 1, ok
statusline live home                -> [fleet:a3ad]  sup held 44m  4 bodies ...
statusline dogfood home             -> [fleet:c3e5]  idle 1 2h
`fleet status` here lists df-hello? -> 0
```
Guard armed, revival path rescued by the profile edit, two fleets distinguishable in the bar,
isolation holds. **That is item 1's DONE definition met, except `fleet init` in a repo (dispatched).**

## RUNNING
- `w63-sidunion` (item 2) — the sid-union join, keeper + profile guard.
- `w63-initrepo` (item 1) — `fleet init` inside a repo creates a home there, from `aee5fdf`.
- Floor on `aee5fdf`, both interpreters, one clone, serial. Predicted **5025 collected,
  `6 failed, 5002 passed, 16 skipped, 1 xfailed`** (the statusline lane's measured figure; my two
  commits touch only an already-tracked `docs/operator/` file and the exempt gates file).

## NOT DISPATCHED, ON PURPOSE
- **fleet.py split research (item 5)** — operator asked, brief is ready, but it is a report lane and
  the directive caps me at two Opus build lanes with a third only for item 1. Goes out the moment a
  slot frees.
- **G-K1 (item 3)** — keeper work; `w63-sidunion` owns `bin/fleet_keeper.py` this wave.

## ONE-LINE LESSONS
- The statusline lane's first full suite was **28 failed, not 6**: 22 were line-number self-citation
  pins and `[fleet]`-literal assertions in files that never mention the statusline. "It is a
  renderer change" was wrong — budget re-pins on any change to a rendered literal.
- Absence of a process is not absence of a job: I read an empty `pgrep` as a memory kill while `uv`
  was still building the env, and ran two suites in one clone. Third run proved the overlap harmless.

THROUGHPUT wave 62-63: bin +414/-68, tests +833/-93, docs +2407/-10, journal +433; operator items
advanced: 1 (statusline home tag, the append, guard verified), 2 (sid-union dispatched).

## 2026-09-10T12:04:15Z CHECKPOINT inc=inc-20260910T075355Z-4f99 sid=cf4ffa2b-da13-4a9d-8d0b-57656c0f572f

WAVE 63 LANDED AND PUSHED (`aee5fdf..708fa45`). Half the wave is now on Codex — the twelve
efficiency rules and the Codex directive are adopted and this checkpoint is written under them.

## SHIPPED
- `1de9995` statusline home nameplate; `a0cae87` profile G-K7 A; `aee5fdf` **the homes-list append**
  (G-K7 discharged by doing, not ruled); `708fa45` **`w63/sid-union`** — the claim→roster join is
  the sid union, `sup-status --json` publishes `claim_sids`, interface guard amended.
- **Floor ONCE per interpreter on the merge, per rule 11: 5058 collected, `6 failed, 5035 passed,
  16 skipped, 1 xfailed`, IDENTICAL failure sets on 3.10 and 3.12.** Predicted 5058 before running
  (4978 + 47 statusline + 33 sid-union). Hit exactly.

## THE MERGE COST, RECORDED BECAUSE IT RECURS
The only conflict was **12 line-number self-citations in ONE docstring** — the w53 shape, where
neither side is correct for the merged tree. Resolved to HEAD, re-derived with
`tools/repoint_self_citations.py aee5fdf` (37/44), then the sid-union enumeration corrected 14 → 15
sites. **I verified byte-wise that ONLY digits changed** before trusting that tool — w53 measured it
deleting 21,774 CR bytes while reporting success; it did not fire here (LF host). 30 citation pins
and 588 keeper/supervisor tests green before the merge commit.

## CODEX IS RUNNING — TRACK 1, NOW
- `mcx gur6MwBB gpt-6-astra /home/altai/proga/fleet-w63-doctrine` — docs-currency rule + efficiency
  rules 3–12 as doctrine + `tests/test_docs_currency.py` (seeded RED first) + the JOURNAL board roll.
- `mcx nSsQ6ufB gpt-6-astra xhigh /home/altai/proga/fleet-w63-split` — the `fleet.py` split research.
- **Gotcha the next body must not repeat: the SUPERVISOR must not export `MCX_WORKER=1`.** That is
  the lane-side recursion guard; setting it on myself got `mcx: workers cannot launch or steer
  workers`. Ambient is unset. mcx state lives in `<cwd>/.mcx/`, so spawn FROM the lane worktree.

## BLOCKED
`w63-initrepo` **LIMITED, resets 14:10:00Z** (now 12:03Z) — the Claude plan wall for the second time
in one wave, which is the whole argument for moving work to Codex. Watcher armed on both Codex
workers and that horizon.

## DECIDED (overturnable, per rule 4 — no gate raised)
- The sid-union lane's gate draft (the `supervisor-stalled` page instructs `sup-spawn` for a body
  the interface guard then refuses) is **not parked**: it is a wording collision inside two files we
  own, not ratified spec text. It goes to the doctrine lane's follow-up.
- G-K5 item (2) is unblocked now the append is made; `w63-initrepo` resumes on it at the horizon.

## TWO ERRORS OF MINE THIS WAVE, ONE LINE EACH
- The earlier `7 failed` floor was **my contamination**: I ran `homes --add`, `autoclean` and
  statusline probes against the live home while a full suite was reading it. Clean re-run: 6.
- Before that I ran two suites in one clone after misreading an empty `pgrep` as a memory kill.
  Both are the same error — disturbing the thing I was measuring.

THROUGHPUT wave 63: bin +531/-96, tests +1290/-93, docs +3400/-10, journal +560; codex: 2 workers;
operator items advanced: 1 (statusline nameplate, append, guard verified — DONE but for `fleet init`
in-repo), 2 (sid-union join landed).

## 2026-09-10T12:54:35Z CHECKPOINT inc=inc-20260910T075355Z-4f99 sid=cf4ffa2b-da13-4a9d-8d0b-57656c0f572f

WAVE 63 CONTINUED — doctrine + keeper-pane landed and pushed (`708fa45..fb2a863`). Three Codex
workers ran this segment; two have landed. First real red of the wave found and fixed.

## SHIPPED
- `7ec4f87` doctrine: efficiency rules 3–12 + the docs-currency rule (`CLAUDE.md`),
  `tests/test_docs_currency.py`, `docs/CHANGELOG.md`, SPEC §0 line-count fixed.
- `4923e16` journal board roll: 3 checkpoints live, 12,574 lines to `journal-history/2026-07-to-09.md`.
- `d9e8c1f`/`8e530a7` keeper finds the interface by REGISTERED PANE, never window name.
- `fb2a863` re-pin the live `check-ignore` receipt.
- **Floor 5087, `6 failed, 5064 passed, 16 skipped, 1 xfailed`, IDENTICAL on 3.10/3.12.**

## THE RED WAS REAL AND THE HARNESS CAUGHT IT
The keeper lane added ONE comment line to the top of `.gitignore`. `git check-ignore -v` prints the
matching LINE NUMBER, and `docs/specs/claim-nonce.md`'s `# live:` receipt quotes
`.gitignore:15:supervisor/*.tmp`. It became `:16`. **A one-line comment in an unrelated file
reddened a spec receipt three files away** — sha-pinned receipts are immune by construction, `# live:`
ones are deliberately not. Re-pinned; `verify_receipts --self-test --strict` 0 failures both seeds.
**Note for reading future reds: my previous `7 failed` was my own contamination and the cheap
inference was "same again". It was not — this one reproduced IDENTICALLY on both interpreters, which
concurrent live-host mutation does not do. That difference is the discriminator.**

## CODEX, MEASURED OVER THREE LANES
- `gur6MwBB` doctrine (astra/high) — 467 checks, journal split sha-verified.
- `gXy7yHdJ` keeper-pane (astra/high) — pin RED→GREEN, 154 keeper tests both interpreters.
- `nSsQ6ufB` split research (astra/xhigh) — still running.
- **CODEX CANNOT COMMIT: its sandbox makes git metadata read-only.** Every Codex lane ends with the
  supervisor committing on its behalf. Both lanes handled it correctly *because the brief told them
  not to fight the sandbox and to hand over a path list* — put that line in every Codex brief.
- **A Codex lane works on a SNAPSHOT.** `gur6MwBB`'s journal split was correct and sha-verified
  against `708fa45`, but the live journal had a later checkpoint; replaying it would have silently
  dropped one. **Anything mutating a live append-only file must be re-derived at landing, never
  merged.** Caught by comparing line counts against the live file, not by review.

## DECIDED (overturnable)
Accepted the keeper lane's choice to DEFER a tick and page nothing on a malformed pane registration,
against my first instinct to make it fall back: the fallback path can `ensure_window` and recreate
the duplicate this lane exists to prevent. It is a silent, UNPINNED branch on the keeper's only
alerting path — recorded in the commit; next keeper lane pins it.

## OPEN
- **The interface must register its pane** (`tmux rename-window fleet && printf '%s\n' "$TMUX_PANE"
  > state/interface-pane`) or the keeper still uses the window-name path. Notified; not yet done.
- `w63-initrepo` LIMITED until 14:10Z — G-K5 item (2), becomes wave 64.
- `nSsQ6ufB` split research running.

THROUGHPUT wave 63 (708fa45..fb2a863): bin +61/-3, tests +378, docs +291/-202, journal +12624/-12574
(the board roll); codex: 3 workers, 2 landed; claude lane tokens: 0 new (all three lanes were Codex).
Operator items advanced: 3 (keeper-pane fix), and the twelve efficiency rules are now doctrine.

## 2026-09-10T13:57:41Z CHECKPOINT inc=inc-20260910T075355Z-4f99 sid=8aecbcb7-d029-408f-8b8c-33ed75b1ad56

WAVE 63 CLOSED. Board and CHANGELOG refreshed, pushed `798daf0`, THROUGHPUT typed to `work:fleet`.
Woken by the interface on a keeper page that the wave's own fix made safe.

## THE SID-UNION JOIN IS PROVEN IN PRODUCTION, BY THE THING IT WAS BUILT FOR
At 13:54Z the keeper paged `supervisor-stalled ... roster idle under a retired sid` — the NEW reason
clause — and the interface guard correctly read my body as ALIVE and woke me **instead of spawning a
second body**. Twelve hours ago that same shape was a false `supervisor-dead` page whose written
guard would have authorised two live bodies over one GOALS.md. Built, landed, and exercised in
anger inside one wave.

## SHIPPED THIS SEGMENT
- `798daf0` board refresh (30 lines, against `ed715cc`) + CHANGELOG gains keeper-pane and the split
  report. Also scoped `dispatched_tasks` to exclude `sup~<inc>~*.md`.
- `ed715cc` the split report's own DONE line (see below).

## TWO PIN CORRECTIONS, BOTH MINE TO OWN
1. **I pushed a red.** I chained `pytest && git push` in one command, so the push ran regardless of
   the result and `4ec3608` reached the remote with `test_new_lane_documents_have_done` failing.
   Fixed two minutes later in `ed715cc`. **Verification cannot gate an action it is chained to** —
   third time this wave I have collapsed measure-and-act into one motion.
2. **Rule 7's pin covers lane REPORTS, not just briefs.** My brief carried `DONE means:`; the Codex
   worker's report did not. A briefing defect, not a worker defect: **every Codex brief must say the
   REPORT carries the line.** Now in the record.

## DECIDED (overturnable)
`dispatched_tasks` now excludes `sup~<inc>~*.md`. That file is the task dispatched TO a supervisor
body — machine-rendered by `_render_successor_task`/`sup-spawn` with a fixed preamble, not a brief
anyone authors. Rule 7 binds *"every task the supervisor dispatches"*, so this is faithful to the
rule, not a weakening; without it the pin reddens on every boot on a file no lane can edit.

## STATE
Floor **5087, `6 failed, 5064 passed, 16 skipped, 1 xfailed`, identical on 3.10/3.12**. Tree clean,
nothing unpushed. `pending_present` was my own heartbeat rotating the generation (age 5s, not the
3610s the interface saw) — nothing to clear. Interface pane `%3` registered, so the keeper-pane fix
is live. `w63-initrepo` resumes at 14:10:30Z (armed, harness-tracked).

## WAVE 64 — ONE OPERATOR ITEM, HALF ON CODEX
Item 1 finishes with `w63-initrepo` (in-repo `fleet init`). Then item 2's **G-K6 wave-2 waker, which
must sit OUTSIDE the plan-limit blast radius** — measured 08:02Z, a waker inside the limited body
fired in 53s and could do nothing; the keeper's systemd timer makes no model calls and is the only
tier that survives. Codex takes the docs/receipt half. **Not starting the fleet.py extraction: the
report recommends D and that is the operator's to ratify.**

THROUGHPUT wave 63: bin +592/-84, tests +1574/-81, docs +2117/-210; codex 3 workers all landed,
claude lanes 3; operator items advanced: 1, 2, 3, 5.

## 2026-09-10T15:30:11Z SEIZED inc=inc-20260910T153011Z-0a56 sid=4e98bef1-dadd-48ba-845f-d2f61859ecd1

seized from inc-20260910T075355Z-4f99: holder roster-gone, heartbeat stale (5550s > 3600s)

## 2026-09-10T15:31:32Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=4e98bef1-dadd-48ba-845f-d2f61859ecd1

WAVE 64 OPENS. GEN-0 of this generation booted by SEIZE, not a handoff: `inc-20260910T075355Z-4f99`
was roster-gone with a 5550s stale heartbeat (> 3600s). Nothing was in flight on its side — its last
checkpoint (13:57Z) closed wave 63, board and CHANGELOG pushed at `798daf0`, tree clean but for its
own uncommitted journal appends, which this body inherits and will commit at the wave boundary.

## INBOX DRAINED — THE CLAUDE FREEZE IS ADOPTED
`state/inbox/20260910-claude-freeze.md` → `state/inbox/done/`, campaign line appended. Operator
ruling 2026-09-10T14:2xZ, verbatim: *"opus as supervisor, no more anthropic workers, use mcx for now
only ... weekly limit will only reset on the 15th, we are already at 77% usage"*. Binding on this
generation and every successor until the operator lifts it through the interface:
1. Supervisor Opus; successors Opus.
2. **Every lane on mcx `gpt-6-astra`. No `fleet spawn` of a Claude worker, no `resume-limited`.**
   `w63-initrepo` STAYS PARKED — its brief is re-dispatched on mcx from the current tree instead.
3. Codex cannot commit; the supervisor commits on its behalf. A Codex lane works on a SNAPSHOT, so
   anything mutating a live append-only file is re-derived at landing, never merged.
4. Supervisor turns are the scarce resource: dispatch, review, land, push, checkpoint. No essays.
Rule 5's lessons half already landed at `47b8e69` (`#2026-09-10-claude-freeze`, committed by the
interface); this checkpoint is its JOURNAL half.

## STATE AS FOUND
- `autoclean` (with `--fleet-home`, two fleets on this host): archived 0, skipped 30, 0 errors.
- Roster 36 entries / 3 live; no mcx worker running in any wave-63 worktree.
- Floor of record: **5087 collected, `6 failed, 5064 passed, 16 skipped, 1 xfailed`, identical on
  3.10/3.12** at `fb2a863`. Unmeasured since; re-measured at this wave's merge.
- Open from wave 63: interface pane `%3` registered (keeper-pane path live).

## WAVE 64 PLAN
1. **Item 1's last piece** — bare `fleet init` inside a repo creates a home there. `w63-initrepo`'s
   brief re-cut for mcx against `47b8e69`, run from a fresh worktree.
2. **Item 2 — G-K6 wave-2 waker**, which must sit OUTSIDE the plan-limit blast radius: measured
   08:02Z, a waker inside a limited body fired in 53s and could do nothing. The keeper's systemd
   timer makes no model calls and is the only tier that survives.
3. Not started: the `fleet.py` extraction (report recommends D — operator's to ratify) and G-K1.
