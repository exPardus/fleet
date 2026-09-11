## 2026-09-10T15:49:25Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=4e98bef1-dadd-48ba-845f-d2f61859ecd1

WAVE 64 MID — three operator rulings arrived mid-wave and are adopted; lane 1 landed; three lanes
live, which is the new ceiling exactly.

## THE RULINGS, AS THEY NOW STAND (later ones supersede earlier)
1. **Reap at every wave boundary** (15:5xZ) — SUPERSEDED IN PART by its own AMENDMENT.
2. **AMENDMENT (16:0xZ): reaping is a FLEET MECHANISM, not a supervisor chore.** *"autoclean should
   just run when doing the supervisor stand down or supervisor boot process, not be done by the
   supervisor itself."* Supersedes rules 1 and 4. **Until it ships the supervisor does NOT reap by
   hand** — so my boot `autoclean` (archived 0, skipped 30) is the last one I run. Rules 2 and 3
   STAND: **max 3 live worker sessions, Claude and Codex counted together; no dispatch under 1.5 GB
   available.** Checked before both dispatches this segment: 5030 MB available.
3. **Standing directive (16:1xZ): mechanise every ritual.** *"everything that can be handled by
   scripts and code should not be done by the harness or model."* Default is CODE; MODEL needs a
   written justification.

## THE OOM IS THE REASON, AND THE NUMBERS MATTER
15:18:08Z, OOM killer on the claude daemon scope: daemon down (`cause=signal`, `live_workers=12`),
every Claude session dead including the supervisor body — **that is what I seized from.** The 12 were
4 retired supervisor bodies + 8 idle finished workers at ~350 MB each. **`fleet autoclean` is 0-for-30
on exactly those rows** (measured by the interface): `--ttl-hours` defaults to 24 and every corpse was
younger. The mechanism needs its own criterion; that is the lane's hardest part, and it is briefed.

## LANDED
- `2f48827` / merge `ef35df1` — **bare `fleet init` creates a home in the cwd** (G-K5 Reading A).
  171 targeted tests per interpreter on 3.10.21/3.12.14, plus real-subprocess smoke in /tmp repos
  including a path with spaces. **`resolve_home` and `apply_resolved_home` proved byte-identical to
  `47b8e69` by whole-function source comparison** — Reading B stays unbuilt, and the lane proved it
  rather than asserting it. Conservative branch taken on the one real decision: **bare init does NOT
  append to the machine-global homes list**, because multi-fleet §Definitions makes a home initialized
  by a parsing `state/fleet.json`, not by list membership. Gate drafted below, not raised.
- **MERGED LOCALLY, NOT PUSHED.** The floor runs on the merged tree at wave close and the push
  follows it. Wave 63 pushed a red by chaining `pytest && git push`; verification cannot gate an
  action it is chained to.

## LIVE (3 = the ceiling)
- `MTHXKmsn` w64-waker — G-K6 wave 2, the wake mechanism outside the plan-limit blast radius.
- `yTsyPhu4` w64-reap — the AMENDMENT's mechanism. Fenced hard off `sup-boot` against the live home:
  that verb mints a claim and would seize it from me.
- `oKE6prPc` w64-rituals — the CODE/MODEL audit table, docs-only, so it cannot collide with the two
  lanes editing `bin/`.

## GATE DRAFTED, NOT RAISED (mine to carry)
Does G-K5 Reading A mean bare `fleet init` creates an initialized cwd home **without** machine
registration, leaving registration to `init --home` / `homes --add`? If automatic registration is
intended, its irreversible E2 tier and command shape need ratifying plus a §5 table amendment.

## NEXT
`wave-close`, `sup-guard`, `interface-register` and the journal board roll are batch-1 items not yet
dispatched — they all edit `bin/fleet.py`, so they queue behind `w64-reap` rather than fight it.

## 2026-09-10T15:52:19Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=4e98bef1-dadd-48ba-845f-d2f61859ecd1

WAVE 64 — TWO MORE RULINGS ADOPTED, AND ONE DECISION OF MINE THE OPERATOR MAY OVERTURN.

## RULINGS
- **mcx 0.2.0 (16:4xZ)** — `mcx spawn --wait` backgrounded by the harness replaces every poll loop.
  I had three `mcx list`+`sleep 60` loops alive; killed them and re-armed on blocking `tail --pid`
  waits against each lane's `mcx _run` pid, which is what the already-running lanes allow (`--wait`
  attaches at spawn only). No new dispatch of mine will use a poll loop.
- **Codex budget (16:5xZ)** — *"dont spam astra ... we burned also 75% of the codex weekly limit
  too."* Default is now `gpt-5.6-luna` at `-r medium`; `-r high` only for a build lane touching
  `bin/fleet.py`; astra only where failure on 5.6 is nameable in advance, with the reason in the
  dispatch line; never for docs, tests, receipts, reports, folds. **Waves are 1-2 lanes.**

## DECIDED (OVERTURNABLE) — I have THREE astra lanes live, against the new 1-2 wave rule
All three were dispatched BEFORE the 16:5xZ ruling. Rule 4 exempts in-flight astra lanes by name but
names only two of mine (the operator wrote the list from what they could see; `w64-reap` and
`w64-rituals` went out at ~16:3xZ). **I am letting all three finish rather than killing two.**
Reason: killing a lane mid-run discards every astra token it has already spent and buys nothing back
-- the spend is sunk, the remaining spend is the tail. Re-dispatching them on 5.6 would cost MORE
total Codex budget than letting them land. **I am dispatching nothing further this wave**, so the
wave ends at 3 and the next one starts at 1-2 on 5.6. If the operator would rather I stop two now,
say so and I will.

## HOST WARNING RAISED, NOT ACTIONED — IT IS NOT MINE TO ACTION
`pgrep` shows **9 mcx lanes live on this 8 GB box: 3 mine, and 6 in `/home/altai/proga/tap`** which
belong to another session. 506 MB free, 4496 MB available. **The 15:18Z OOM happened at 12 sessions.**
The operator's 3-lane ceiling is a HOST ceiling, but `fleet status` cannot see the tap lanes and I
have no authority over that directory -- so I notified `work:fleet` and stopped dispatching. Folded
into `knowledge/projects/claude-fleet.md` as a standing fact, because the next generation will read
`fleet status`, see three rows, and believe it has headroom it does not have.

## SHIPPED THIS SEGMENT
`a737fa8` doctrine fold: `skills/fleet/supervisor.md` (freeze supersedes the Opus/Codex split; mcx
0.2.0 mechanics; the model budget) + `knowledge/projects/claude-fleet.md` (the OOM with its measured
numbers, autoclean 0-for-30 and WHY -- `--ttl-hours` defaults to 24 and every corpse was younger, so
an age-based sweeper cannot reap the only kind of corpse that can OOM you).

Still merged-not-pushed: `ef35df1` (init-in-repo). Floor and push at wave close, in that order.

## 2026-09-10T16:58:29Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=4e98bef1-dadd-48ba-845f-d2f61859ecd1

WAVE 64 CLOSED AND PUSHED (`47b8e69..e7ab9ec`). Four lanes, all on Codex, zero Claude worker tokens.
Floor **5216 collected, `6 failed, 5193 passed, 16 skipped, 1 xfailed`, IDENTICAL on 3.10 and 3.12.**

## SHIPPED
- `2f48827` bare `fleet init` creates a home in the cwd (G-K5 Reading A). Conservative on
  registration: no machine-global append. `resolve_home`/`apply_resolved_home` proved byte-identical
  to `47b8e69` by whole-function comparison -- Reading B stays unbuilt and the lane PROVED it.
- `851e797` G-K6 wave 2, the keeper wake, OFF BY DEFAULT.
- `f22a672` the reap mechanism + its regression fix.
- `395015c` the 220-row CODE/MODEL ritual table.

## THE FLOOR EARNED ITS COST THIS WAVE — 15 FAILURES, NOT THE 6 I PREDICTED
**The one that matters: `sup-release` REFUSES to tombstone an ambiguous identity -- *"guessing would
retire another body's record"* -- and the new reap pass, running immediately after, removed one of
the records it had just refused to touch.** A new mechanism reaching around a deliberate safety
refusal, invisible to the lane's own 695 targeted tests because they never ran the two together.
Cause: at an exit sweep the claim is already released, so holdership can no longer protect the
caller and its rows read as "predecessor-supervisor". Steered the warm lane with the reproduction;
**it found `sup-handoff-complete` had the identical hole** and fixed both at the shared protection
layer. The veto is scoped to the caller's own pass, so a later body still reaps a real dead
predecessor.

## THREE ERRORS OF MINE, ONE LINE EACH
1. **The gate I raised did not parse, twice.** First I put the question in the body and "Ruling owed"
   in the checkbox; then I put the `?` inside the bold so the line ended `?**`. The assertion is
   `endswith("?")`. I fixed the half I had noticed instead of reading the assertion -- the same
   measure-and-act collapse my predecessor recorded three times last wave.
2. **My census edit reddened seven citation pins one commit after I had fixed them.** Expanding a
   self-citing comment from 3 lines to 10 shifted every cited line below it by +7. `repoint_self_citations.py`
   correctly REFUSED to help (positional map, count moved 45->48). Remedy: make the edit
   line-count-neutral. **A comment edit in `bin/fleet.py` is measured in LINES ADDED before it is
   measured in words.**
3. **I led a host warning with `free` when the metric is `available`** -- 506 MB free while 4783 MB
   was available and PSI was zero. The interface corrected me; pinned in `knowledge/projects/claude-fleet.md`.

## WHAT I CORRECTED IN A LANE'S WORK
The reap lane **deleted 55 lines of Watchtower-beat doctrine** and replaced them with an 18-line
summary. The instruction was genuinely dead, but three findings inside were not: the §7 exemption
must be carried explicitly at every frame; a bare `fleet archive` on the beat is a byte-identical
repeat; `--dry-run` does not disarm §7 because the gate is on the CALLER. Restored verbatim under a
dated SUPERSEDED header. **A deletion is not a supersession.** Not the lane's fault -- my brief
asked it to make the brief describe the mechanism and said nothing about the history underneath.

## HOST
The harness's BACKGROUND-task memory guard killed two full floor runs within seconds at 4947 MB
available and zero PSI -- it appears keyed on `free` (2029 MB), the same confusion the interface
corrected in me. **Remedy that worked: run the floor in the FOREGROUND, split in halves, plus
`tests/integration` which `ls tests/test_*.py` silently misses (9 skips, and their absence made my
first split total 9 short).** Nine mcx lanes were live host-wide, six of them the operator's in
`/home/altai/proga/tap` and not mine to stop.

## GATE RAISED, NOT PARKED
**G-K8**: the keeper wake writes to the Claude daemon's PRIVATE local socket, against standing goal
3's "zero writes to foreign surfaces". Stated fairly both ways -- every CLI-only path fails the case
B exists for, and the contract is measured against installed Claude 2.1.267 and can change silently.
Not parked: nothing is blocked, the feature is inert until installed.

## SUCCESSOR QUEUE
Batch 1 of the mechanise-rituals directive: `fleet wave-close`, `sup-guard`, `interface-register`,
and **the journal board roll, which is a live defect** (`bin/fleet.py:17746` appends without rolling;
I hand-rolled it this wave and it reddens again at every fourth checkpoint). Waves of 1-2 lanes,
default `gpt-5.6-luna`.

THROUGHPUT wave 64 (`47b8e69..e7ab9ec`): bin +522/-95, tests +961/-30, docs +901/-35, journal
+421/-242, other +145/-1; codex 4 lanes (1 steered), all landed; claude worker tokens: 0; operator
items advanced: 1 (DONE), 2, 3, 4; gates raised: 1 (G-K8); reaped: 0 rows (the mechanism ships this
wave; the supervisor no longer reaps by hand).

## 2026-09-10T17:35:08Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=4e98bef1-dadd-48ba-845f-d2f61859ecd1

WAVE 65 CLOSED AND PUSHED (`07042d5..c50258a`). One lane, on the CHEAPER default model, both its
deliverables landed. Floor **5228 collected, `6 failed, 5205 passed, 16 skipped, 1 xfailed`,
IDENTICAL on 3.10 and 3.12** (+12 collected, all from the new verbs' own tests).

THROUGHPUT wave 67 (593e927..e4222e138094e676aef9578ac8d33247cdfec9f9): bin +35/-6, tests +84/-0, docs +40/-1, journal +0/-0, other +37/-8; workers: 30; tokens: UNMEASURED; reaped: 0

## SHIPPED — `5d659ad`
- **`fleet journal-roll`, CALLED BY `sup-checkpoint`.** The board self-maintains now. Losslessness is
  done by partitioning the ORIGINAL BYTES, and the roll REFUSES on malformed UTF-8 or unparseable
  headers rather than reshaping a file it could not read. History goes to a new stable sink
  `supervisor/journal-history/journal-roll.md`; this wave's two hand-rolls are in `2026-07-to-09.md`.
  Two append-only files, no lost bytes — worth knowing before someone greps one and thinks it is all.
- **`fleet interface-register`** — idempotent, accepts only the keeper's `%<decimal>` pane shape,
  writes `state/interface-pane` ONLY after tmux succeeds, refuses clearly with no tmux.
- The lane ran the citation fixpoint ITSELF (36 of 48 against `07042d5`) instead of leaving it for
  landing. First lane on `gpt-5.6-luna` under the budget ruling and it needed no steering.

## THE HOST FACT THAT COST A LANE, AND THE RULE THAT REPLACED MY REMEDY
I followed the 16:4xZ notice and backgrounded `mcx spawn --wait`. **The lane was spawned and read
`stopped` seconds later.** Two documented facts compose: cancelling a `--wait` waiter stops its run
and children, and **this harness kills background commands on a guard keyed on `free` (253 MB), not
`available` (4147 MB, PSI zero)** — the same guard that killed two full floor runs within seconds.
I reported it with the measurement; **the interface accepted it and tightened the rule past my own
remedy**: not merely "drop `--wait`" but **no background waiter at all** — lanes stay DETACHED and
are polled with `mcx list` / `mcx result` at natural turn points. *A waiter you do not need is a
shell you are paying for on a box that kills shells.* Folded into both surfaces a fresh generation
reads (`b2ba94a`) and into the host file (`f0f0ee8`).

## STANDING REMEDIES NOW WRITTEN DOWN, BECAUSE EACH COST ME A RUN
- **Run the floor in the FOREGROUND, split into halves.** Backgrounded full runs die to the guard.
- **`ls tests/test_*.py` silently misses `tests/integration`** — 9 skips, and their absence made my
  first split total exactly 9 short of the full-suite figure. Always append `tests/integration`.
- **The split is alphabetical, so new test files move the boundary**: `head -46` covered 2671 tests
  last wave and 2269 this one. Use `tail -n +47`, never a second fixed count.

## STATE
Tree clean, nothing unpushed, no lane running. Board at 3 checkpoints and now self-maintaining.
Context ~2xx k, below the 350k band.

## SUCCESSOR QUEUE — in priority order
1. **`fleet wave-close`** (directive batch 1, the big one): reap pass, floor per interpreter from a
   fresh clone, THROUGHPUT computed from `git diff --numstat`, CHANGELOG + JOURNAL prepends, commit,
   push with the 3-retry rule, notify. The supervisor would supply only a base sha and the CHANGELOG
   sentences. **Note for whoever briefs it: the floor half must use the foreground/split/integration
   discipline above, or the verb will inherit the bug that cost this generation four runs.**
2. **`fleet sup-guard`** — the interface's two-live-body guard as one verdict line, with `--do`.
3. G-K8 is open and blocks nothing; G-K1 (keeper as a feature flag) is still unbuilt.

THROUGHPUT wave 65 (`07042d5..c50258a`): bin +223/-30, tests +325/-4, docs +140/-12; codex 1 lane on
`gpt-5.6-luna` (astra: 0), landed without steering; claude worker tokens: 0; lanes lost to the
harness guard: 1, cause found and ruled; operator items advanced: 4 (two batch-1 verbs).

## 2026-09-10T18:51:39Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=849fc7ef-b8aa-47d2-bad2-ba896aa0deab

WAVE 66 OPEN. Woken by the interface on a keeper `supervisor-stalled` page (heartbeat 73 min stale,
roster idle) — the guard correctly read this body as ALIVE and woke it instead of spawning a second.

## THE PAGE IS THE SYMPTOM OF SOMETHING I CAN FIX WITHOUT WAITING FOR G-K6
Same shape as 13:54Z: **a generation closes a wave and nothing gives it the next turn.** I closed
wave 65 with a THROUGHPUT notify and ended my turn — correct by the old rule, and it produced 73
minutes of dark fleet and a page. The interface's instruction, adopted now and carried in my body
journal: **end every wave close with `sup-notify "SUPERVISOR: wave N closed, idle until woken"`** so
the interface wakes me deliberately rather than the keeper discovering it. That is a stopgap until
G-K6's waker is ruled (G-K8), and it costs one line per wave.

## DISPATCHED — 2 lanes, both `gpt-5.6-luna` `-r high`, both DETACHED
- `mkWzhGsK` **w66-guard** — `fleet sup-guard` with `--do`. Briefed hard on the one behaviour that
  matters: **a body that is alive and listed must never produce `DISPATCH`.** Pointed at the
  interface profile as the SPECIFICATION to mechanise rather than a policy to reinvent, at
  `rule_supervisor_stalled`'s reason clauses as the verdicts to correspond to, and at the views
  doctrine — bare `sup-guard` is a VIEW: no lock, no probe, no write, no quarantine. Asked it to say
  whether it must join `tests/test_views_doctrine.py`'s scope list.
- `WGSE2Pvv` **w66-wave-close** — the big one. Its floor arm carries the six things this generation
  lost four runs learning, written into the brief so the verb does not ship the bug: foreground not
  background, split in halves, `tests/integration` is missed by the obvious glob, the split boundary
  moves as files are added, fresh `git clone --no-local`, both interpreters identical — and
  **verification cannot gate an action it is chained to**, so its push arm must be gated on a PARSED
  floor result and abort rather than warn.

Both edit `bin/fleet.py`. **The merge owes ONE citation fixpoint pass, not two** — each lane runs the
tool against `1556986` itself and hands over which citations it touched.

## NOT STARTED, ON PURPOSE
G-K8, the `fleet.py` split pilot and G-K1 are with the operator. The interface named them; I am not
touching them.

## STATE
Floor of record **5228 collected, `6 failed, 5205 passed, 16 skipped, 1 xfailed`, identical on
3.10/3.12** at `1556986`. Tree clean, nothing unpushed. Memory 5076 MB available at dispatch, above
the 1.5 GB floor; 2 fleet lanes live, under the 3-lane ceiling. Body journal now exists at
`state/journals/sup~inc-20260910T152948Z-f976~boot.md` per the task file.

## 2026-09-10T20:31:05Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=c15ed5b3-079c-4a4a-8f00-568d2792cae0

WAVE 66 CLOSED AND PUSHED (`1556986..ca41ed7`). **MECHANISE BATCH 1 IS COMPLETE.** Two lanes, both on
`gpt-5.6-luna`, both landed. Floor **5245 collected, `6 failed, 5222 passed, 16 skipped, 1 xfailed`,
IDENTICAL on 3.10 and 3.12**.

THROUGHPUT wave 68 (116860f..8ab8e08849c4dc43e3cab584cd218099b6d8cc9d): bin +346/-71, tests +323/-128, docs +2167/-145, journal +69/-40, other +247/-2881; workers: 30; tokens: UNMEASURED; reaped: 0

## SHIPPED
- `6327ea9` **`fleet sup-guard`** — one verdict line for the two-live-body question. A stale claim
  whose body is alive and idle, **including one visible only under `retired_sids`**, yields `WAKE`,
  never `DISPATCH`; only a stale HELD claim with no live body dispatches; everything ambiguous
  (seized, unknown, fresh-heartbeat gap, handoff in flight, releasing body still roster-live,
  unavailable union) PAGES. Bare `sup-guard` is a VIEW and the lane **added it to the D4 pin's scope**
  rather than sitting outside the fence that makes the doctrine checkable. `--do` re-observes
  immediately before acting, because the gap between deciding and acting is where a second body is born.
- `b737c24` **`fleet wave-close`** — the whole boundary as one verb. Its floor arm INHERITED this
  generation's four lost runs instead of rediscovering them: foreground, one sorted recursive
  `tests/**/test_*.py` walk (so the halves cannot drift and `tests/integration` cannot be missed),
  fresh clone, both interpreters compared, and **it ABORTS rather than warns** when the totals or the
  failure set differ. That is the wave-63 `pytest && git push` defect answered in code.
- **The best part of that lane's report is what it REFUSED to automate**: CHANGELOG wording, progress
  -row acceptance and expected-failure-set maintenance all stay MODEL, *"because filenames and DONE
  text do not establish semantic acceptance"*. A verb that invented those would be worse than the
  ritual it replaces. Its effect-table class is deliberately UNCLASSIFIED and fail-closed until the
  operator ratifies it.

## THE MERGE COST, AND A TOOL THAT REFUSED CORRECTLY
Nine conflicts: **eight pure line-number self-citations where NEITHER side is right for the merged
tree** (the w53 shape), and one real content conflict in the SPEC command table where BOTH rows were
wanted. `repoint_self_citations.py` **refused** — the guard lane added three sid-union sites so the
count moved 48→51, and a positional map would have mapped three wrong numbers onto three right ones
in silence. Re-derived instead from the citation suite's own assertion messages, which name
cited-vs-real for every stale site; ten citations moved, every edit a digit-for-digit substitution.

## THE FLOOR CAUGHT A CENSUS PIN, AND THE TWO NAMES WERE DIFFERENT KINDS
`_sup_guard_live_rows` and `_wave_roster_claude_tokens` were in neither the census nor the exclusion
list. **Filing both the same way was the easy wrong answer.** The first is CENSUSED — a real Q1
reader the whole guard rests on, and note it requires a non-empty pid and ignores `done` rows,
because status alone is not evidence of life: the w61 finding arriving at a new caller under its own
power. The second is EXCLUDED — it sums tokens for THROUGHPUT and never asks whether anything is
alive; `roster_` in its name is the shape matching, a name-shaped false positive of the same kind as
`_multi_fleet_population_is_live`.

## MINE TO OWN
Wave 65's board shipped at 32 lines against a ≤30 cap and I let it pass. This one is inside it.

## THE PAGE PATTERN, NOW ANSWERED TWICE OVER
Third `supervisor-stalled` page in one generation, all the same shape: a detached lane finishing does
not wake me. Interface instruction adopted: **end every dispatch turn with a `SUPERVISOR:` line
naming the lane ids and expected duration**, and every wave close with `wave N closed, idle until
woken`. Both are stopgaps until G-K8 rules on the waker — and `sup-guard` now at least makes the
interface's side of the page one command instead of five.

## SUCCESSOR QUEUE
1. **`wave-close` has never run for real.** Built, tested targeted, but its commit/push arm could not
   be exercised end-to-end in the Codex sandbox. Its first real use is the next wave's close — run it
   deliberately, with the hand path ready, and report what it got wrong.
2. Second batch of the directive: keeper pages carrying the guard verdict, the timer-generated daily
   gate docket, lesson-folding skeletons, handoff bundle assembly.
3. Operator-held: G-K8, the `fleet.py` split pilot, G-K1.

THROUGHPUT wave 66 (`1556986..ca41ed7`): bin +651/-31, tests +245/-3, docs +94/-3, other +81/-41;
codex 2 lanes on `gpt-5.6-luna` (astra 0), both landed unsteered; claude worker tokens: 0; merge
conflicts 9 (8 citation, 1 content); operator items advanced: 4 — **batch 1 complete**.

## 2026-09-10T21:01:09Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=524b9901-f57c-4726-b95f-b89b42c0c5c0

WAVE 67 CLOSED AND PUSHED (`593e927..713f058`). One lane landed, and **`fleet wave-close` ran for
real for the first time and produced three defects** — which is exactly why it was queued to be run
rather than trusted.

THROUGHPUT wave 69 (f8cc8c2ef63369812729f302fb0b321aa1b06cd9..0ae383d5f0fed3b620e214f642f545e6a780ab96): bin +291/-66, tests +118/-4, docs +34/-0, journal +117/-66, other +9/-0; workers: 1 (w69/wave-close-accounting: claude); tokens: UNMEASURED (roster has no token field); reaped: 0; protected: 1 (unread mail)

## SHIPPED
- `a1b04cb` **`sup-guard`: a seize is an EVENT IN THE PAST, not a state.** It was printing
  `PAGE claim seized` against a healthy fleet — my claim was seized at 15:30Z, so every verdict for
  five hours would have paged. Now seized+fresh flows through the ordinary held-claim rules;
  seized+stale still pages; both directions pinned. The lane answered the sibling-clause question
  instead of skipping it: no other branch treats a past event as a state.
- `8a8d086` + `713f058` **the wave-close repairs** (below).

## THE THREE DEFECTS, IN THE ORDER THEY SURFACED
1. **The floor never ran.** It invoked `python3.10 -m pytest` directly; NO interpreter on this host
   has pytest importable. **My briefing defect** — I gave the lane six hard-won findings about
   foreground-vs-background, the recursive walk and the moving split boundary, and omitted
   `CLAUDE.md`'s FIRST rule, how the suite is invoked at all. The lane had even set `UV_OFFLINE` and
   `UV_CACHE_DIR`, so it knew uv was in the picture; nothing told it the interpreter alone cannot work.
2. **A floor that never ran was indistinguishable from a floor that ran clean.** A half with no
   pytest summary parsed as zero of everything, and zero failures compares EQUAL to an empty expected
   set. It aborted only because the expected set is the six host assumptions — **had it been empty,
   the push would have been licensed by a floor that never executed.** Now it raises and names the log.
3. **`git commit` died on an unset committer identity**, after the reap and both floors — twelve
   minutes of work with the landing prepared and staged. Every commit this generation made passed
   `-c user.name=...`, so nothing had ever exercised the repo config. Repo identity set; and the verb
   now checks `git var GIT_COMMITTER_IDENT` with the cheap preconditions. **Same lesson as moving the
   `uv` lookup ahead of the clone, arriving twelve minutes later and more expensively: check what the
   expensive work depends on BEFORE doing the expensive work.**

**The abort is what makes this a good story rather than a bad one.** At every step the verb refused
to land on a result it could not reconcile. Nothing wrong was pushed.

## WHAT IT GOT RIGHT, MEASURED
- **The reap ran for real: 24 rows** — retired supervisor bodies and finished lane workers back to
  w58, including the 15:18Z OOM corpses. First live exercise of the operator's amendment.
- Both floors ran, matched, and the THROUGHPUT line computed with **`tokens: UNMEASURED`** rather
  than a fabricated zero. The rule held under machine authorship.

## A DESIGN FINDING THE NEXT BODY MUST PLAN AROUND
**`wave-close` takes ~12 minutes, longer than the 600s tool timeout**, so from a Claude Code session
it is ALWAYS pushed to background — which is where the harness low-memory guard lives. It survived
this time. It needs to be resumable, or to run its floors concurrently, or the close needs to be
split. It is also **not idempotent across a failed close**: it had already prepended and staged the
CHANGELOG and JOURNAL, so re-running would have duplicated them. I committed its prepared content by
hand instead.

## PINS ADDED
Three, on the floor arm, because every pre-existing wave-close test injects `run` and neither defect
was reachable from them. **A verb whose expensive arm is only ever mocked is a verb whose expensive
arm is unpinned.**

## NEXT
Batch 2 directive received (five verbs, prose caps, `tokens_per_bin_line` and `external_lines` in
THROUGHPUT). G-K8 ruled **option C**: the socket path comes out, the waker goes through `fleet send`
built on `sup-guard --do`, keeper wake on by default — one astra lane, wave 68. Tier policy stays
**top=opus** per the correction; no PROPOSAL to move it.

## 2026-09-10T21:04:28Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=c8677549-1ea9-4c1e-a8ac-ab65b25aca52

WAVE 68 OPEN — the prose-rot campaign, phase 1 (context-loaded files).

MEASURED at `713f058`, confirming the directive: `docs/` 92,635 md lines, 38,907 of them in 68 lane
reports; `knowledge/` 2,565 (lessons.md 2,033); `skills/fleet/supervisor.md` 587; CLAUDE.md 36 but
mostly corrections of itself; profile 143; GOALS.md 133; 68 history phrases in `bin/fleet.py`.

I am a producer of this rot, not an observer of it. The lane reports being archived are ones I
commissioned, and my checkpoints are the same genre. Checkpoints get shorter from here.

DISPATCHED, both `gpt-5.6-luna` high, detached, observers armed:
- `BqtwsRwm` w68-skill — `skills/fleet/` becomes the operating manual, <=400 lines total, imperative,
  verbs derived from `build_parser()` rather than from any existing doc. This is the operator's
  "more instructions" ask.
- `SsvzANTe` w68-caps — CLAUDE.md <=60, profile <=100, briefs <=60, loaded knowledge <=400 with
  entries <=12, lessons >30d to `docs/archive/`, and `tests/test_prose_caps.py` pinning EVERY cap
  including the ones later lanes must satisfy, xfail with the lane named. A cap nobody wrote down is
  a cap nobody meets.

ONE CONSTRAINT I DID NOT LET THE CAMPAIGN OVERRIDE: `supervisor/GOALS.md` is 133 against an 80 cap,
but it is operator-owned and no lane may originate its content. The lane writes a proposed trim to
`docs/operator/goals-trim-proposal.md` and I carry it as a PROPOSAL. The cap is pinned xfail meanwhile.

QUEUED, NOT DROPPED: G-K8 option C (socket path out, waker via `fleet send` on `sup-guard --do`,
keeper wake on by default) — one astra lane, next wave. Batch 2's five verbs after it.

BRIEFS ARE NOW UNDER ONE SCREEN, per the new prose caps. Mine had been ~80 lines.

THROUGHPUT wave 70 (64da0aa2331543958825cee4abffc29b8f94b5b5..e9a394efcd9d4c3de2531c90072550572209f9fd): bin +257/-61, tests +104/-9, docs +38/-0, journal +72/-61, other +0/-0; workers: 2 (w70/keeper-pane-live: codex, w70/substrate-and-board: codex); tokens: UNMEASURED (roster has no token field; mcx result files missing); reaped: 0; protected: 1 (unread mail)

THROUGHPUT wave 71 (7f7722fcaf31fb5f3aaa31a5522beb5a56db4958..1a58339a6a62c37d7152f67e94c668fcda6446d3): bin +254/-564, tests +694/-844, docs +157/-101, journal +0/-0, other +21/-3; workers: 1 (w71/gk8-waker: codex); tokens: UNMEASURED (roster has no token field; mcx result files missing); reaped: 0; protected: 1 (unread mail)

## 2026-09-10T22:42:04Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=819e3008-5862-4e86-b01c-993ecfc50bfe

WAVE 68 CLOSED AND PUSHED (`116860f..16f28c5`). The prose campaign's phase 1 landed and
`fleet wave-close` closed a wave end to end for the first time.

THROUGHPUT wave 72 (7162ce901b1565a72741cf81df146638ffaf25a8..613da18eb170a62f884f403bffda2d726ed8ecf7): bin +41/-11, tests +56/-3, docs +0/-0, journal +42/-33, other +0/-0; workers: 0 (none); tokens: UNMEASURED (roster has no token field); reaped: 0; protected: 1 (unread mail)

THROUGHPUT wave 73 (d3ab326156336b734970ad4548f02cce3c225ac0..ae53bf8451a6479bdd2859dea47f3e37efbe312f): bin +24/-21, tests +87/-9, docs +51/-4, journal +0/-0, other +2/-2; workers: 1 (w73/guard-verdict-table: codex); tokens: UNMEASURED (roster has no token field; mcx result files missing); reaped: 0; protected: 1 (unread mail)

THROUGHPUT wave 74 (b0f6e02de112b92a2c7ebceb80463c8a98f8d7d8..1d9920d5423b8ac8e49c383a0217a6757d96cfb2): bin +4092/-12961, tests +1003/-262, docs +137/-5, journal +0/-0, other +15/-0; workers: 5 (w77/keeper-multihome: codex, w76/split-extract: codex, w75/split-contract: codex, w74/code-prose: codex, w74/docs-archive: codex); tokens: UNMEASURED (roster has no token field; mcx result files missing); reaped: 0; protected: 0 (unread mail)

## SHIPPED
- `314ea3e` `skills/fleet/` is a 160-line operating manual; `supervisor.md` (587) and
  `docs/operator/server-interface-profile.md` deleted, their current content absorbed. It teaches the
  INTERFACE AS A ROLE: "become" and "continue" are the same six steps, because the role's state lives
  in the home and never in a conversation.
- `efc4b5c` context-loaded files under cap, lessons >30d archived, `tests/test_prose_caps.py` pinning
  every cap including the four later waves must close, xfail with the lane named.
- `b0b5370` interface state in the home; bare `init` registers the caller; the §7 gate follows the
  home being INITIALISED so a claim elsewhere no longer blocks `init` in an unrelated repo.

## THE CAMPAIGN KEEPS FINDING DEFECTS THAT ARE NOT ABOUT VERBOSITY — SIX NOW
A keeper that would have gone SILENT on any host with no registered pane (only alerting tier, early
`return 0` before paging); a keeper `--profile` default aimed at a file the same wave deleted;
`fleet init` refused in unrelated repos by a foreign claim, breaking the ruling's headline scenario;
doc-claims auditing the archive as a claim about the current tree; a receipt greping a lesson that
had moved to the archive; and the wave id below. **The operator's "full of inconsistencies" was
literal.** Deleting prose keeps exposing places where prose was load-bearing and nobody had said so.

## `wave-close` EARNED ITS KEEP AND THEN MISLABELLED ITSELF
It ran both interpreter floors from a fresh clone, found the receipt failure the campaign had
introduced, and REFUSED to land or push. Second run: green, committed, pushed, relayed. Then it
labelled wave 68 as `wave 67`: `_wave_id` took the max from the FIRST matching file, JOURNAL.md, and
**the board roll shipped in wave 65 had migrated the highest wave number into journal-history**. Two
mechanisms built two waves apart, neither wrong alone. Fixed to take the max across board, changelog
and every history file. The mislabelled commit is pushed and stays: rewriting shared history to fix a
label is the worse trade.

## MY OWN DEFECTS THIS WAVE
- I shortened briefs to meet the new prose cap and dropped the offline uv invocation, so THREE lanes
  reported "pytest blocked" and one shipped a keeper regression untested. **A cap on brief LENGTH
  must not drop the line that makes the work verifiable.** Clause now saved for verbatim reuse.
- "Targeted tests" was read by lanes as "the tests I wrote". Briefs must name the suite per file
  touched.
- I passed `--base 116860f`, a checkpoint rather than the close commit, so the range double-counted.

## DISPATCHED
`yT3qCJAa` w69-wc (5.6 luna) — the interface's six remaining wave-close accounting defects plus the
board's pending-rulings computation. The one that matters most: **wave-close must refuse to close
when a merge since base has no CHANGELOG line** — an unrecorded landing is invisible forever.

## OBSERVERS DID NOT FAIL
Every observer fired and I acted on each. The 68-minute idle was AFTER the last lane, during landing,
and ended with my turn over and the wave still open. Re-arming would not have helped: nothing was
left to observe. That gap is what G-K8 option C's waker closes; it is now the third page it would
have prevented.

## 2026-09-11T00:11:43Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=3768eb9a-c4c8-40de-b37c-e735b28a2bce

Wave 69 closed+pushed f8cc8c2..64da0aa. wave-close ran clean end-to-end: correct wave id, base from
the previous close commit, lane named, UNMEASURED naming its missing source, protected:1 explaining
the surviving corpse. Two aborts first, both my defects (Docs trailer on a bin+skills commit; a lens
file with no DONE line) -- the gate caught both.
Defect for w70: THROUGHPUT substrate says `claude` for w69/wave-close-accounting, which ran on mcx
gpt-5.6-luna. Detection is wrong.
sup-guard seize fixed on the right axis (settlement, not freshness); live claim returns
`PAGE roster says busy`. G-K8 C unblocked.

## 2026-09-11T08:18:29Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=b7dfb271-39ae-4a5f-b528-a0efe5f841ba

Wave 72 landed three fixes; first live wake through the G-K8 C path arrived and this body continued
from it (sid rotated, so fork-steer ran). Live-wake receipt is PARTIAL: state/keeper/last-page.json
holds no supervisor-stalled/wake key, so keeper authorship is unconfirmed -- the wake may have come
from the interface. Full receipt still owed at a keeper-authored wake.
Pre-steer processes are gone: roster has 3 live-pid rows and neither c3de1414 nor 38f399b5 is among
them, consistent with retirement-after-live-fork.

## 2026-09-11T14:14:02Z CHECKPOINT inc=inc-20260910T153011Z-0a56 sid=719199e0-5b26-47e2-ac4f-1871c95f3303

HANDOFF. Context 745,934 vs the 400,000 hard ceiling (§11.3) -- well past it; nothing in flight, tree
clean, everything pushed through 6537949. No lanes running; tap holds 1 session, 2 lanes of host
headroom.

SUCCESSOR PICKS UP FIRST
1. Mechanise batch 2's remaining verbs: `fleet land`, structured lane results (docs/lanes/<lane>.json),
   `fleet brief`, computed checkpoint/boot-bundle, knowledge caps.
2. tap-driven work as its departments hit walls -- that is now half the fleet-repo agenda, and the
   multi-home keeper (1d9920d) means tap's supervisor is watched.

BLOCKED ON THE OPERATOR, DO NOT WORK AROUND
- docs cap xfail at 19,542/15,000. The w74 archive pass met the number by moving LIVE specs that
  tests enforce; I restored them. Closing this needs a ruling: raise the cap, or name which specs are
  history. Do not archive a live spec to hit a number.
- GOALS cap xfail: `docs/operator/goals-trim-proposal.md` is ready; only the operator commits GOALS.md.
- G-K8 C receipts: keeper-authored wake unconfirmed (state/keeper/last-page.json carries no
  supervisor-stalled key), per-wake token cost UNMEASURED (roster has no token field).

HOST RULES THAT COST ME TIME -- they are in skills/fleet/SKILL.md and knowledge/projects/claude-fleet.md
- Lanes DETACHED, observer breaks on rc != 2 (`mcx result`: 2 live, 0 done, 1 stopped/unknown).
- Floor in the FOREGROUND, split in halves; derive both halves from ONE sorted recursive walk.
- Every brief must carry the offline test invocation verbatim, and must name the SUITE per file
  touched -- "targeted tests" gets read as "the tests I wrote", which is how a silent keeper shipped.
- Verify lane reports at landing. Three lanes this generation reported done on work that was not.

## 2026-09-11T14:14:17Z HANDOFF-BEGIN inc=inc-20260910T153011Z-0a56 sid=719199e0-5b26-47e2-ac4f-1871c95f3303

successor=inc-20260911T141417Z-699c task=/home/altai/proga/fleet/state/supervisor-handoff-inc-20260911T141417Z-699c.md

## 2026-09-11T14:14:45Z HANDOFF-COMPLETE inc=inc-20260910T153011Z-0a56 sid=719199e0-5b26-47e2-ac4f-1871c95f3303

claim -> inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

## 2026-09-11T14:14:59Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

claim received via handoff from inc-20260910T153011Z-0a56

THROUGHPUT wave 75 (6537949ace0b3cb25808e086057c1d497b93a37e..5e2d14cc728caffa2a21bc2d9c041f2342a2502d): bin +346/-1, tests +166/-4, docs +127/-0, journal +122/-71, other +156/-6; workers: 2 (w78/fleet-land: codex, w79/knowledge-caps: codex); tokens: UNMEASURED (roster has no token field; mcx result files missing); reaped: 0; protected: 0 (unread mail)

## 2026-09-11T14:20:01Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

Wave 75 dispatched, 2 lanes, base e87c049. w78/fleet-land (bu8raFEv, luna high): `fleet land <lane>` as leaf bin/fleet_land.py + docs/lanes/<lane>.json contract -- mechanise batch 2 items 1+2; sole bin/fleet.py writer this wave. w79/knowledge-caps (6pqOeS32, luna medium): tools/knowledge_index.py, item 5; fenced off bin/fleet.py and SKILL.md.
Brief defect caught pre-dispatch: a fresh UV_CACHE_DIR under UV_OFFLINE=1 cannot resolve pytest. Both briefs now name /tmp/w64-initrepo-uv-cache, the one populated cache on this host. docs-currency pin green against the dispatch home before dispatch.
Context 110k/350k at dispatch; available 3812 MB; observers armed detached per lane, break on rc != 2.

## 2026-09-11T14:36:59Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

w79/knowledge-caps landed (merge b6c1d20 -> server/persistent-fleet). tools/knowledge_index.py: --check exits 1 on a stale index, --write regenerates, --roll-lessons appends dated lessons >30d verbatim. Verified by me in the worktree, not from the report: 205 passed / 2 xfailed on 3.10 and 3.12 both; the 2 xfailed are the pre-existing docs-cap and GOALS-cap items. INDEX.md content unchanged -- the generated index matches the hand-written one once placeholders are excluded.
Lane reported DONE the first time with a JSON carrying no test rc and a report citing results 'recorded in the handoff' (no handoff exists), and it had indexed projects/.gitkeep into the file the boot bundle reads. One steer fixed all three. The verify-at-landing rule earned its cost again.
Over-cap on-demand notes MEASURED, none moved: campaign-template 238, claude-fleet 114, pmbot 50, claude-oracle 21, stupidbox 20, spawn-etiquette 14 (cap 12). w78 still running.

THROUGHPUT wave 76 (5f50ac0b3d1d4c8719cfa7911107ecb14d62f73a..2255cc2f9cf562792c8cdcedcc39b8d3785578a6): bin +230/-8, tests +169/-6, docs +99/-0, journal +24/-12, other +61/-0; workers: 1 (w80/fleet-brief: codex); tokens: UNMEASURED (roster has no token field; mcx result files missing); reaped: 0; protected: 0 (unread mail)

## 2026-09-11T15:30:59Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

Wave 75 CLOSED and pushed: 6537949..5e2d14c, 5f50ac0. bin +346/-1, tests +166/-4, docs +127/-0. Landed: fleet land + docs/lanes/<lane>.json contract (batch 2 items 1+2), tools/knowledge_index.py (item 5), SKILL.md --nonce list fix.
Floor REFUSED the first close on 10 failures vs the 6-failure host baseline, both new defects from w78 and both missed by MY brief's suite list (it named neither test_round7_defect_pins nor test_sid_collision): fleet_land.py shipped outside tests/fleet_sources.IMPLEMENTATION_FILES, so no census scanned it and every install built from that tuple carried a fleet.py whose top-level fleet_land import died; and the land verb shipped with no effect disposition. Fixed in 5e2d14c. A new verb needs the effect-disposition pin and a new bin/ module needs the census tuple -- put both in every brief that ships either.
Then found closing: the worktree pruner asked merge-base against the wave's BASE, so it called this wave's own landed lanes unmerged and could only ever prune one wave late. Fixed + pinned in 569411d.

## 2026-09-11T16:02:15Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=e061dbdf-894a-48cc-a9c3-e1c31ca40d09

Wave 76 dispatched: one lane w80/fleet-brief (NtCl32NP, luna high) at base 6cfdd28 -- fleet brief as leaf bin/fleet_brief.py, carrying the product.md Serves: citation and REFUSING a citation whose phrase does not occur under the named section, plus a pin scoping the requirement to task files from 2026-09-11T21:00Z so wave 75 and earlier stay grandfathered. One lane only: everything left in batch 2 writes bin/fleet.py and the one-writer rule holds.
Brief carries the two shipping requirements wave 75 taught: a new verb needs an entry in UNCLASSIFIED_BY_THE_RATIFIED_TABLE, a new bin/ module needs tests/fleet_sources.IMPLEMENTATION_FILES. Both suites named.
BLOCKER RAISED, mine to own: 569411d is red on test_docs_currency::test_branch_docs_currency -- bin/fleet.py changed with a trailer naming knowledge/, and the lint takes only docs/ or a literal Docs: n/a. Green at 5f50ac0, so I introduced it. It blocks every wave close until it ages out of the 20-commit window. Decision raised: amend+force-push (recommended) vs widening the lint. I did not widen it myself: it would clear my own violation.

## 2026-09-11T16:52:47Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=e061dbdf-894a-48cc-a9c3-e1c31ca40d09

Wave 76 CLOSED and pushed: 5f50ac0..2255cc2, close 950678a, host rules e95f57f. bin +230/-8, tests +169/-6, docs +99/-0; one lane. Landed: fleet brief with a VERIFIED product.md Serves: citation (absent phrase, right phrase under the wrong section, and no citation each refuse with exit 1; valid exits 0 -- I ran all four), the dispatched-task pin scoped from 2026-09-11T21:00Z so wave 75 and earlier are grandfathered, and the docs-currency surface widened to docs/ + skills/ + knowledge/ per the operator ruling B.
The wave-close pruner fix from wave 75 is PROVEN: worktrees removed 3 (w78, w79, w80 with their branches), skipped 5 (1 genuinely unmerged, 4 dirty). Under the old base comparison this wave own lanes would all have been called unmerged and kept.
Four failed closes before this one, all mine, all refused before the commit/push phase: changelog cited the lane sha not the merge sha; I monitored a wrapper pid, read its death as the close finishing, and started a SECOND concurrent close; I rm -rf the live close working clone thinking it stray; and I rotated the generation mid-flight with sup-heartbeat. All four rules now in knowledge/projects/claude-fleet.md.

THROUGHPUT wave 77 (950678a1694452ce2a91ac3b0b9df11e98cc6e76..baf28a14f8b3b7d1ffe99906d5165da1771a497f): bin +77/-44, tests +21/-11, docs +83/-0, journal +32/-14, other +17/-6; workers: 1 (w81/band-gate: codex); tokens: UNMEASURED (roster has no token field; mcx result files missing); reaped: 0; protected: 0 (unread mail)

## 2026-09-11T17:23:55Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

Wave 77 dispatched: w81/band-gate (J15MrUc2, luna medium) at 10c24f3. The band gate the manager asked for is an EXTENSION, not a new mechanism: _ceiling_refuses_dispatch (bin/fleet.py:2100) already refuses at the hard 400k ceiling and is already wired into spawn :4229, send :5116, respawn :5414 and :5638, sup-spawn :12779. The lane adds the soft 350k arm, --force-band overriding SOFT ONLY, and occupancy in the sup-checkpoint header. Brief points at those line numbers rather than describing the behaviour.
Named three constraints that outrank the feature: --force-band must not pass the hard ceiling (own test), the structural exemptions and the fail-toward-band rule for unknown occupancy survive unchanged, and the handoff verbs stay exempt -- a gate that blocks the remedy is worse than no gate.
The third path the instruction named does not exist: fleet only READS mcx records for token accounting (:11421, :11475); mcx lanes are dispatched by hand. Told the lane to confirm by grep and report it, not to build one. First brief validated through fleet brief: the Serves: citation passes.

## 2026-09-11T17:39:40Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

Wave 77: w81/band-gate merged b2a8dc7. Soft-band refusal live on spawn/send/respawn/sup-spawn; --force-band clears soft only and is structurally unable to clear the hard ceiling (gated on verdict == in-band, pinned by its own test). Verified 999 passed/4 skipped on 3.10, 769/1 on the 3.12 subset.
Lane changed four verbs and left skills/fleet/SKILL.md untouched though its CLI list claims to be derived from build_parser(); I added --force-band to all four lines and stated what it cannot override. Same doc-gap class as the --nonce list earlier this generation -- worth a standing brief line: a lane that adds a FLAG updates the CLI list, not just a lane that adds a verb.
MEASURED and reported by the lane: there is no mcx dispatch helper to gate.

## 2026-09-11T18:10:10Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

HANDOFF. Context 323,770 vs the 350,000 soft band -- clean boundary, wave 77 closed and pushed (950678a..baf28a1, close bc18650), nothing in flight, tree clean, no lanes running.
SUCCESSOR PICKS UP FIRST: (1) batch 2 item 4, computed checkpoint/boot-bundle; (2) the measurement the batch-2 directive asked for and three waves have not delivered -- every THROUGHPUT this generation reads tokens: UNMEASURED, so spend per landed bin/ line is still unknown; (3) tap work as its departments hit walls. Items 1 and 2 both write bin/fleet.py and serialise.
Full pickup list, blockers and the host rules that cost me time: state/journals/sup~inc-20260911T141417Z-699c~successor.md. The three floor catches this generation shared one cause -- suite lists chosen from memory -- and docs/lanes/BRIEF-TEMPLATE.md now derives them instead.

THROUGHPUT wave 78 (f19fa02..9c802d1d4381ae59143c332bca06e9ea420cfffe): bin +150/-20, tests +94/-0, docs +102/-0, journal +30/-12, other +0/-0; workers: 1 (w82/throughput-measured: codex); tokens: 2734534; tokens_per_bin_line: 18230.23 (2734534 tokens / 150 added bin lines); external_lines: 0 (MEASURED: 1 landed lane(s), all worktrees of this repo); reaped: 0; protected: 0 (unread mail)

## 2026-09-11T18:10:25Z HANDOFF-BEGIN inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

successor=inc-20260911T181025Z-881b task=/home/altai/proga/fleet/state/supervisor-handoff-inc-20260911T181025Z-881b.md

## 2026-09-11T18:10:55Z HANDOFF-COMPLETE inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

claim -> inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

## 2026-09-11T18:11:02Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

claim received via handoff from inc-20260911T141417Z-699c

## 2026-09-11T18:15:28Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

Wave 78 dispatched: w82/throughput-measured (iudZ2FAd, luna medium) at f19fa02. The measurement three waves called UNMEASURED is a wrong-directory bug, not a missing source: _wave_codex_tokens (bin/fleet.py:11497) globs the MAIN repo's .mcx while lanes write theirs in their own worktrees -- /home/altai/proga/fleet/.mcx has 1 record and 0 results, fleet-w64-reap/.mcx has both, and its events.jsonl last line carries turn.completed usage the existing fallback has never reached. _wave_landed_lanes (:11480) already resolves each lane's worktree; that join is what the token reader is missing.
Claude side is a real gap, not a bug: the agents roster has no token field, but state/outcomes/*.jsonl rows carry input_tokens/output_tokens and the registry carries tokens:in=/out=. Brief orders a bounded fallback and makes the lane state its wave bound in code.
Three constraints outrank the feature: never invent a number (a MEASURED zero for external_lines must be spelled differently from an unmeasured one), _wave_token_pair keeps every shape it accepts today, and tokens_per_bin_line must name its denominator. Accounting at :11794 must not move after the prune at :11843, which deletes the evidence. Suites derived by grep, not recalled: test_wave_close, test_liveness_readers, test_round7_defect_pins, test_self_citations.

THROUGHPUT wave 79 (638878b..831f7f82cfbeb3d8fe0ac50814ef52ef44338ba8): bin +233/-22, tests +97/-0, docs +97/-0, journal +31/-20, other +0/-0; workers: 1 (w83/computed-board: codex); tokens: 2819275; tokens_per_bin_line: 12099.89 (2819275 tokens / 233 added bin lines); external_lines: 0 (MEASURED: 1 landed lane(s), all worktrees of this repo); reaped: 0; protected: 0 (unread mail)

## 2026-09-11T18:45:10Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

Wave 78 closed and pushed, 638878b, tree clean, in sync. THROUGHPUT carries real numbers for the first time: tokens 2,734,534; tokens_per_bin_line 18,230.23 (2734534 / 150 added bin lines); external_lines 0 (MEASURED: 1 landed lane, a worktree of this repo). Four waves of UNMEASURED were a wrong-directory read, not a missing source.
My own external_lines fix was wrong and its unit test passed anyway -- a lane worktree is a SIBLING of the repo root, so path containment called this very lane external; the live call disagreed. Resolution through git worktree list is the discriminator. Exercise the verb, never the test alone.
Three consecutive fleet land refusals were all taught by BRIEF-TEMPLATE.md (result path is the branch's FIRST component, the JSON lane field is that component not the kind, blockers is a landing gate that exits RED); fixed at 0eb8886.

## 2026-09-11T18:46:09Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

Wave 79 dispatched: w83/computed-board (SzNKYyTY, luna medium) at 638878b -- batch 2 item 4, the last of the batch. Evidence is this incarnation's own boot: the 240-line bundle left me reading the predecessor journal and the standing directive and running six state commands before I could clear a dispatch gate, all of it computable; and sup-checkpoint accepted a nine-line body against the doctrine's three without complaint.
Brief carries the three fleet land traps explicitly (lane field is the branch's first component, result files named for it, blockers is a RED gate) so this lane does not re-buy last wave's three refusals, and orders the lane to exercise its code against the real repo rather than trusting a unit test.

THROUGHPUT wave 80 (c05d6c3..d6a06652e9bbe7282fc78b121acc784296e9b8cd): bin +79/-36, tests +33/-5, docs +126/-0, journal +25/-13, other +0/-0; workers: 1 (w84/homes-inventory: codex); tokens: 4186837; tokens_per_bin_line: 52997.94 (4186837 tokens / 79 added bin lines); external_lines: 0 (MEASURED: 1 landed lane(s), all worktrees of this repo); reaped: 0; protected: 0 (unread mail)

## 2026-09-11T19:15:45Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

Wave 79 closed and pushed c05d6c3; batch 2 discharged with per-clause evidence. 12,099.89 tokens per added bin line, down from 18,230.23.
w83 executed none of its own tests (sandbox had no DNS); I ran them and found four defects, the worst an unanchored DISCHARGED that matched the words not discharged and silently dropped live directives from the board it was building.
Fleet-side batch work is done; next source of work is tap unless the operator directs otherwise -- standing directive 20260910-standing-directive-throughput says stop feeding the machine itself.

## 2026-09-11T19:18:50Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

Wave 80 dispatched: w84/homes-inventory (UVX152Jj, luna medium) at c05d6c3 -- operator item 1, the first in three waves. Directive 20260910-standing-directive-throughput 4 is explicit: waves 78 and 79 advanced no item on the fixed 1-5 list, so the next wave is item 1 only.
MEASURED in-process, no verb run: resolution_population gives 2 homes, homes_population gives 1, and _refuse_wrong_home_destructive (bin/fleet.py:3163) builds ONE message from both -- it says this machine runs 2 fleets, prints both paths, then embeds a view showing one. The operator's inventory surface contradicts the guard that refuses their commands.
Raised the tap registration to the operator rather than doing it: the homes-list append is ratified destructive, and tap is live with its own supervisor but unregistered.

## 2026-09-11T19:55:13Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

Wave 80 closed and pushed ee2b756, operator item 1 advanced -- fleet homes and the arming guard now count the same homes. 52,997.94 tokens per added bin line, up from 12,099: the wave landed 79 bin lines, and the per-line figure is noisy at that size.
Filed the G-K5 registration gate at 191d3cd -- the one the ruling told the lane to file rather than build around. bin/fleet.py:4225 confirms bare init creates without registering, which is exactly why tap is a live home invisible to fleet homes, and why item 1's DONE criterion cannot be met as written.
My briefs, not the substrate, are why three lanes shipped untested code: UV_OFFLINE=1 with the warm cache works offline on both interpreters; I had dropped the flag. BRIEF-TEMPLATE.md now names the pair.

