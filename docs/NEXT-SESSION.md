# Next session — handoff (written 2026-07-30 ~13:20Z by the interface session, waves 11–32)

## THE LONG-TERM GOAL, unchanged, and where it now stands

**Launch-ready; completion criterion is MULTI-FLEET.** That work is no longer a stub: it is
`docs/specs/multi-fleet.md` **v8, seven adversarial gate rounds complete (14 lens reports,
every finding measured or refuted by execution), DOCKETED for the operator** — the top open
item in `docs/OPERATOR-GATES.md`. The gate loop does not terminate itself (every round returned
GATING while the kill surface shrank from architecture to mechanics), so the operator is the
terminus. **Your multi-fleet job is: carry the docket; when Altai rules ready-for-build, the
build slices are the spec's own Sequencing §3 (slice 0 install/home split first; the global
`--fleet-home` flag lands in or before the arming slice). If a round 8 is ordered, fence all
14 prior reports (`state/journals/mf-r*`) BY FILENAME RE-DERIVED FROM DISK.** Do not redesign;
the architecture (registry-lookup resolution, homes list, verb-effect tier) survived five
consecutive rounds and three directed attacks.

## TWO HARD RULES, unchanged

1. **Never run `fleet sup-boot`** — sup-spawn a body; the claim belongs to a role, not to you.
2. **Never directly drive a worker.** The supervisor owns every worker. You own the plan, the
   operator channel, and read-only verbs. Councils/lenses dispatch THROUGH the supervisor via
   `send supervisor @file` steers specifying independence.
   *One boundary note from this session:* `env -u CLAUDE_CODE_SESSION_ID … kill <dead-sup-husk>`
   was used ONCE, on a dead claim-holder whose nonce died with it — the documented §7.2 escape,
   for supervisor-tier wedges only. It is not a worker-driving precedent.

## FIRST ACT — the fleet is MID-RECOVERY, not idle

At handoff time: **wave-32 attempt 2 (`sup|inc-20260730T131736Z-a61b|boot`) was just dispatched
into an open seize window.** The machine restarted ~12:5xZ, killing wave-31 mid-merge and the
previous interface process. Sequence for you:

1. `fleet sup-status` — if a NEW incarnation holds the claim with a fresh heartbeat, wave 32
   seized and is recovering; watch (`fleet wait <name> --any` in background Bash).
2. If the claim still names `inc-20260730T121408Z-8b77` (dead sid `ef093d27`) and no body is
   working: the wave-32 body hit `freeze` again — heartbeat must exceed 3600s before a boot can
   seize; `fleet sup-spawn --task @state/tasks/lens/sup-brief-wave32.md` once `sup-status` says
   seizable.
3. **The fleet home working tree is deliberately MID-MERGE**: branch `stage-w31`, MERGE_HEAD
   `bacf939` (`w30/cites`), `UU bin/fleet.py` with ZERO conflict markers (resolution done,
   never staged), `tests/test_self_citations.py` added, JOURNAL dirty with wave-31's
   uncommitted checkpoints. **Do not reset it; do not finish it yourself.** The recovery
   runbook is `state/tasks/lens/sup-brief-wave32.md`: pins print the truth
   (`TestRetiredSidWritersAreWhereTheyAreCited` + the new self-citations test), floors both
   interpreters, commit, push.

**Wedge runbook, proven twice this session:** dead claim holder → `fleet kill <its record>`
(no-sid form if the gate is armed) → body tombstoned, claim FROZEN → wait until
`sup-status` says "seizable in 0s" (heartbeat >3600s) → `sup-spawn` seizes. A `freeze` boot
verdict means you spawned before the window opened; the body stops itself correctly — just
re-spawn after.

## Operator's standing directives (unchanged)

Work fully autonomously; push main at every green milestone; keep builders saturated via the
supervisor; short interactive steers; 4-councilor council (through the supervisor) for
operator-gated blocking items; you own the plan.

## State at handoff — RE-MEASURE, never inherit

- `main` = **`a934a10`** local == origin at last successful fetch. **Network is FLAPPING**
  (per-attempt stochastic: DNS-fail / TCP-timeout / success — retry, read no trend from
  either direction, push unpiped, `ls-remote` read-back).
- Suite at a934a10: **3472 passed / 14 skipped / 1 xfailed**, identical both floors
  (`py -3.13` AND `py -3.10`, serially — floors run SERIALLY, the concurrent-run anomaly was
  never characterised).
- Session total: **~85 commits on main since `09dcc2c`**, suite 2811→3472. Merged this
  session: the whole inherited queue + ultrareview P0-2, P1-3/5/6/8/9/10/14, fleet q M2
  (stage-w10a), succession-signal, the out= root-cause fix, the CLAUDE.md quarantine-clause
  correction, and more. Ultrareview remaining: **P1-4 (branch `w30/p14` @ 3d2f24e READY —
  read `fleet result w30-p14` first, it is lossless), P1-13+P1-12, P1-7(=P2-8, review
  double-counted), P2/P3 tiers.**
- Roster ~60 rows, mostly idle husks; three `resid-probe*` workers are DOCKET EVIDENCE — do
  not sweep. `fix/b6-interface-release` (2e824ea) is OPERATOR-GATED by its own commit
  message. `fix/outcome-usage-provenance` is a DECOY branch pointing at main (the real work
  merged; wave-27's release note explains).

## WORKTREE HELL — operator-ordered cleanup (2026-07-30, in-session)

**~80+ worktrees have accumulated** (counted 64→66→69→~80 across one day by four different
measurers; `git worktree list | wc -l` for today's truth) and the operator has ordered the
next session to fix it. Shape of the fix — a supervisor lane, not interface hand-work:

1. **Census + classify**: for each worktree, (a) is its branch an ancestor of `main`
   (`git merge-base --is-ancestor`)? (b) is its tree clean? (c) does it hold anything
   unpushed/uncommitted (the wave-31 lesson: a "stale" worktree held finished work)?
   Ancestry answers a different question than content — grep introduced symbols for anything
   suspicious, per the wave-25 lesson.
2. **Remove clean+landed ones** (`git worktree remove`, then `git worktree prune`); list-only
   for anything dirty or unlanded — those go to the operator or a recovery lane, never
   silently deleted. Known keeps until their work lands: `C:/proga/fleet-wt/w30-p14`
   (P1-4, ready-unmerged), anything wave 32 is actively using.
3. **Standing rule to adopt so this never recurs**: a lane that merges a branch REMOVES its
   worktree in the same wave; lens worktrees are removed at harvest once the report is
   persisted to `state/journals/`. Put it in every supervisor brief until it sticks.

## OPEN OPERATOR GATES — carry these, nothing narrows while they wait

**THE DOCKET CLEARED 2026-07-30.** All four items below were ruled in-session by Altai and are
in `docs/OPERATOR-GATES.md` under `## Settled`; `## Open` is now empty, which is a legitimate
state and not a parse failure. Kept here, struck, because the *follow-ups* they created are
live work:

1. ~~**Multi-fleet v8 ratification**~~ — **RATIFIED ready-for-build.** Build starts at
   Sequencing §3 slice 0 (install/home split), with the round-7 defect pins as slice
   conditions. Rider ruled separately: `fix/b6-interface-release` gets a gate lane, merge on
   green.
2. ~~**Identity clause**~~ — **REPLACED by the substitution model**, ratified as
   `docs/specs/claim-nonce.md` §18. §17 stays as the record of the 2026-07-27 ruling; its head
   sentence survives, its scope half is falsified. Owed follow-ups DONE in wave 34: the three
   `bin/fleet.py` citations, `_doctor_check_identity_witness`'s remedy (it hunted a stripper
   that does not exist), `DAEMON_ENV_LEAK_REMEDY`, `skills/fleet/supervisor.md` step 5 and
   `skills/fleet/SKILL.md` (the ABSENT-stamp third variant, which is the common case).
3. ~~**§7 exemption envelope**~~ — **RATIFIED as ruled, with the `:2174` repair as a
   condition** (satisfied: the taxonomy row moved 2026-07-28). Three PROVISIONAL markers in
   §7 discharged in wave 34. Still open and NOT covered by the tick: **arm 3** (dispatch over a
   live beating claim-holder) and **arm 6** (deferred, contested 2–2).
4. ~~**Branch-protection vs merge doctrine**~~ — **answered: B** (drop/scope the GitHub rule so
   policy agrees with doctrine; the settings change is the operator's own shell action). The
   `sup-decision` slot is FREE, so outcount2's poll-bound question can take it.

## ONE NEW GATE OWED, raised by wave 34 and not yet put to the operator

**ND4(c) cannot be re-grounded as ordered — the ruling collides with ratified ND4(b).** The
2026-07-30 identity ruling ordered three-tier §11.3 ND4(c) re-grounded off `FLEET_WORKER`
absence and onto "caller sid absent from the registry sid union". That predicate is
definitionally `IDENTITY_UNRESOLVED`, and ND4(b) already governs that exact input with the
opposite verdict (*"an unresolvable identity must never be the reason a ceiling stays
dormant"*). `_ceiling_refuses_dispatch` was therefore left **byte-for-byte unchanged** rather
than improvised on, and the hole is live: a claim-holding supervisor whose daemon was
cold-started unstamped is exempt from the 200k HARD ceiling today (four of four measured
bodies). Three candidates are priced in **claim-nonce §18.4**, with A (narrow (c) so the
claim-holder is never exempt whatever its stamp) recommended — it reads the claim file, not the
environment, so it needs no sound env channel and does not touch ND4(b)'s bucket.

## The revive loop (how this session ran 21 waves)

`sup-spawn --task @state/tasks/lens/sup-brief-waveNN.md` → background `fleet wait <name> --any`
→ on notification read `fleet sup-status` head (the release note IS the handoff) → author the
next brief from it → spawn. **Supervisors often leave no successor brief — author one, one
page, ACT FIRST, merge-before-read, ending with "WHAT THIS BRIEF GOT WRONG — assume it
contains an error and go find it" (paid in 14 consecutive lanes).** Briefs live in
`state/tasks/lens/`, never at `state/tasks/<name>.md`.

## Measured doctrine from this session — reuse, don't re-learn

- **`sup-context` reads the WHOLE window** (~85–110k at boot, spread 24k across four bodies);
  runway to the 150k trigger is ~40–65k. Dispatch in the first 30k, merge before reading.
- **Merge pricing recipe (three refinements deep):** (1) FILE-SET comparison
  (`git diff --stat base..branch`) — empty intersection terminates pricing; (2) hunk-range
  overlap counts CONFLICTS; (3) EXECUTABILITY counts COST — citation-comment conflicts are
  computable (resolve either side, run the pin, re-pin to what it PRINTS — never hand-pick).
  Clean ≈31–40k; conflicted ≈60–65k; disjoint file sets ≈ free.
- **One writing worker per working tree** — two writers collided in wave 27 (worktree add
  `--detach`, since main is checked out). ~80 worktrees exist; use them.
- **`fleet doctor` at supervisor boot** (two supervisors misfiled a live FAIL about their own
  body); the absent-FLEET_WORKER identity-witness FAIL is a KNOWN docketed condition.
- **out= is wrong evidence** (spec'd as final-message tokens; was publishing second-to-last
  message's usage 73% of turns — fix merged, now withholds). Verify report files on disk.
- **Lens fences: deny READS + PUSH, never writes** (a dontask fence denied the deliverable
  itself); enumerate fence files from `ls`/`find`, not memory (15 named, 19 found).
- **Background waits die with host restarts and can be reaped** — verify fleet state fresh on
  every wake; a killed task still notifies, which still wakes you.
- **529 storms**: two stillborn supervisor boots in a row = back off 3m/10m/20m, then retry
  the same brief. A dead mid-turn body with a held claim = the wedge runbook above.
- **Absence-keyed guards**: 88 sites censused (report `state/journals/absguard.md`), one
  confirmed live fail-open universal (ND4c — rides the identity gate). Lane candidates listed
  in wave-25's release note.

## Ledgers

`knowledge/lessons.md#2026-07-30-interface-stress` (the full postmortem + stress-test verdict:
one session clears the queue only because the harness compacts — 471k measured against the
200k ceiling; supervisor boot cost is the binding constraint). `knowledge/INDEX.md` first
entry. Persistent memory: `MEMORY.md` → `multi-fleet-docket-pending`, `interface-tier-runbook`.
Supervisor journal: last TWO release notes only (`fleet sup-status` head is cheaper than the
file). The ultrareview: `docs/reviews/ULTRAREVIEW-2026-07-30.md` (its line numbers are rotted
~85 commits — re-derive from code, always).
