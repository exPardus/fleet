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

