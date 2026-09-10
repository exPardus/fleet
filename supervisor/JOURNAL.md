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
