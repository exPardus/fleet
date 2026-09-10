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
