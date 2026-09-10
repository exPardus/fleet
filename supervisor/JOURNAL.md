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
