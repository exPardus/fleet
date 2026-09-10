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
