# w63-sidunion — the claim→roster join is now the BODY's sid union, in the keeper and in the guard

**Lane:** build (keeper + operator surface). Branch `w63/sid-union` from `64aa96b`, eleven commits:
`ba7fc40` (the build), `72f1975` (pin 1 end to end), `c41e451` (the plain-spelling measurement),
`b6a2beb` (the rule docstring), `338fc86` (pass the claim to the resolver), `1b76726` (the
`claim_sid`-unknown guard), `ab82853`/`cc7f59a`/`81fa544` (the narrow-reader and view pins, and the
rewrite after M10/M11 showed the first version of them was dead), `3e7f448` (the guard's mechanism
sentence, made precise), and this report.
**Every line below is tagged MEASURED (I ran it, on this host, today, 2026-09-10) or
BELIEVED (inference, code reading, or someone else's report).** Host `kz-work`, Linux 6.8.0-139,
`claude` 2.1.267-era roster shapes.

**Scope built:** the union join at TWO sites — `bin/fleet_keeper.py` and
`docs/operator/server-interface-profile.md` — plus the read that makes it possible,
`fleet.supervisor_claim_sids()` published by `sup-status --json`. **No spec edits**
(MEASURED: `git diff --stat 64aa96b..HEAD -- docs/specs/ docs/OPERATOR-GATES.md` is **empty** —
neither the specs nor the gate file is touched). C is not reverted (§4).

**SHIPPED, in one line:** the claim→roster join is the body's sid union at both sites; the union
is published by `sup-status --json` (`claim_sids`) and printed by its human form; eleven mutants
red; the floor is unmoved on 3.10 and 3.12; no spec edit, no gate ticked, one gate DRAFTED for the
operator.

---

## 0. THE ONE-PARAGRAPH ANSWER

**The brief's §4 option (b) — publish the union from `sup-status --json` — DOMINATES option (a),
and I built (b).** It is not merely cheaper: it is the only one of the two whose answer is
*internally consistent*. The keeper's claim sid already comes from `sup-status --json`; resolving
the union in that same call means the union and the sid can never be a fork-steer apart. Had the
keeper resolved the union itself it would have taken a SECOND registry read, at a different
instant from `status_snapshot()`'s, and joined a sid from one process against a registry read by
another. **The brief's §7 asked me to say so plainly if (b) dominated. It does.**

And the brief's §4 premise — *"the keeper cannot currently read `retired_sids`"* — is **true, but
not for the reason implied, and the reason matters** (§2). The keeper is not blocked by D4. It is
blocked because **nothing it reads publishes a sid union at all**, and the one in-process read it
already has (`fleet.status_snapshot()`) publishes **no session id whatsoever**.

---

## 1. WHAT CHANGED

MEASURED, `git diff --numstat 64aa96b..HEAD` — 8 files (this report included), 1436 insertions,
154 deletions. Excluding the report:

| file | +/− | what |
|---|---|---|
| `bin/fleet.py` | +135/−23 | `supervisor_claim_sids()`; `claim_sids` in `sup-status --json`; the retired-sid line in its human form; 39 self-citations re-pointed (§8) |
| `bin/fleet_keeper.py` | +186/−50 | the join, the grading, the reason clauses |
| `docs/operator/server-interface-profile.md` | +16/−4 | guard steps 1/2/3 and the page's reason-clause list |
| `tests/test_supervisor_claim_sids.py` | +251 (new) | 17 pins on the resolver and the publish |
| `tests/test_keeper_rules.py` | +202/−52 | the 10:16Z pins; the efa0 pins re-checked under the union; fixture migration |
| `tests/test_keeper_collect.py` | +181/−24 | the join, end to end |
| `tests/test_keeper_dedup.py` | +2/−1 | fixture migration |

Most of `bin/fleet_keeper.py`'s +186 is docstring and comment; the behaviour is the two-line join
below, `_claim_activity`'s ten-line body, and four reason clauses.

### The join, in one pair of lines

```
-    claim_in_roster = claim_sid is not None and claim_sid in agent_statuses
-    claim_row_status = agent_statuses.get(claim_sid) if claim_in_roster else None
+    claim_rows = {sid: agent_statuses[sid]
+                  for sid in sorted(union) if sid in agent_statuses}
```

`union` is `sup-status --json`'s `claim_sids` (normalised) **plus the claim sid itself**, so w63
can only ever find MORE of a body than C did, never less.

**C's `status == "busy"` grading is untouched and C is NOT reverted.** `_claim_activity` still
classifies four ways and `busy` is still the allowlist of one; what changed is the SUBJECT it
grades — a set of rows belonging to one body, read most-alive-first, instead of one session's row.
**The type normalisation w62-keeperc §4 flags as still load-bearing is kept AND extended**: the
union's members are used as dict keys, so an unhashable member would raise `TypeError` out of the
tick exactly as a dict `session_id` once did. Mutant M3 proves the extension is live (§5).

`claim_in_roster`/`claim_row_status` are **deleted, not redefined**, on w61 §5's own doctrine —
a name whose meaning silently widened from a session to a body is how the next reader inherits
this outage.

### The page text, on the real 10:16Z inputs

MEASURED, both runs driven through `collect` with the real `sup-status`/roster JSON of the event:

```
# at 64aa96b (C, shipped):
KEEPER: supervisor stalled since 61 min ago (heartbeat 61 min stale, claim session not in
the roster). Report state, then relaunch with sup-spawn; do not await the operator.

# at c41e451 (w63):
KEEPER: supervisor stalled since 61 min ago (heartbeat 61 min stale, roster says idle under
a retired sid). Report state, then relaunch with sup-spawn; do not await the operator.
```

The brief asked for the reason clause to be right. `claim session not in the roster` is the defect
restated; `roster says idle under a retired sid` is the true sentence, and it is the one that
tells an operator who greps the roster for the printed sid why they will not find it.

### The live receipt — the branch resolving the REAL body, on the REAL registry

MEASURED 2026-09-10T11:07Z, this branch's `bin/fleet.py` against the live `FLEET_HOME`
(read-only; §11):

```
$ FLEET_HOME=/home/altai/proga/fleet python bin/fleet.py sup-status --json
  claim_sids : ["37e5c61c-…", "42445477-…", "d605e989-…"]
  claim sid  : 42445477-de98-4813-937a-e18c965de740
  inc id     : inc-20260910T075355Z-4f99
  claim_sids inside incarnation? False

$ FLEET_HOME=/home/altai/proga/fleet python bin/fleet.py sup-status
supervisor: inc-20260910T075355Z-4f99 sid=42445477-de98-4813-937a-e18c965de740 via handoff,
heartbeat 1913s ago
  same body, retired sids: 37e5c61c-…, d605e989-… -- a roster row under ANY of these is this
  body alive
```

All three sids, resolved from the live registry record, on the body the incident happened to. No
`fleet.lock` and no `fleet.json.corrupt.*` appeared in `state/` (MEASURED after the runs). Note the
heartbeat: **1913 s stale while the body reads `busy`** — the legitimate-long-turn case C
deliberately suppresses, live, at the moment of writing.

---

## 2. §4 ANSWERED: WHAT THE KEEPER MAY READ, MEASURED, AND WHERE THE BRIEF IS OFF

The brief says it asserted this without saying by what path the keeper reads anything. Here is the
path, MEASURED at `64aa96b`.

**The keeper has exactly four read sources**, three of them subprocesses through the injected `run`
seam and one an in-process import:

| source | how | carries a sid? |
|---|---|---|
| `fleet.status_snapshot()` | in-process (`import fleet`, `bin/fleet_keeper.py:48`) | **NO. Not one.** |
| `bin/fleet.py sup-status --json` | subprocess (`_sup_status`) | yes — `incarnation.session_id` |
| `claude agents --json` | subprocess (`_agents`), never `--all` | yes — `sessionId` per row |
| git | subprocess (`_git_unpushed`) | n/a |

**The finding that corrects the brief: `status_snapshot()` publishes no session id at all.** Its
worker rows carry `name`, `status`, `turns`, `cost_usd`, `mail`, `stale_seconds`, `tier`, … and
**never `session_id` or `retired_sids`** — MEASURED by reading the row literal in
`status_snapshot`. And `snap["supervisor"]` (`_supervisor_tier_snapshot`) is claim-FILE-only by
written mandate — *"no lock, no roster read, no probe, no subprocess"* — and publishes exactly
`goals_active`, `state`, `incarnation_id`, `heartbeat_age_seconds`. **So there was no sid in the
keeper's in-process read to join on, let alone a union.**

**And `cmd_sup_status` did not read the registry either** (MEASURED: it reads `read_incarnation()`
and `read_handshake()` and nothing else). So before w63 **no keeper-visible surface carried
`retired_sids`**, by any path.

**Now the part the brief got wrong.** The brief frames the read as a possible D4 violation —
*"reading the registry to get `retired_sids` may be a new capability for it… if it cannot, that is
a gate"*. **D4 was never the obstacle, and no gate is owed here.** D4 (and CLAUDE.md's standing
RULE) forbid a view **taking `fleet.lock`, probing, writing, or quarantining**. Reading the
registry read-only is not on that list, and `status_snapshot()` — the canonical view — **already
does it**, through `_read_registry_readonly()`. Fleet even ships the named accessor for exactly
this case: `_registry_records_or_none()` (`bin/fleet.py:15970`), whose docstring says it exists
because *"`load_registry` QUARANTINES a corrupt registry — it renames the file aside — which is a
WRITE"*. `supervisor_claim_sids` routes through it, so `sup-status` gains a **read** and no
capability D4 cares about. **Pinned, not asserted:** `test_a_corrupt_registry_is_none_and_is_not_
quarantined` leaves the corrupt file untouched and then proves its own detector can see a real
quarantine; `test_the_union_read_never_takes_the_lock` and `…_is_not_load_registry` record every
call to `fleet_lock`/`load_registry` and assert none happened — a shape they had to be rewritten
into after a mutant showed the raising version was dead (§5, M10/M11).

**So: no gate drafted, and none owed.** §6 asked me to file a draft and stop if the work collided
with D4's narrow-reader rule. It does not collide. What I owe instead is the honest statement that
**`sup-status` is one read wider than it was**, which is in its own comment at the call site and in
§9 below.

---

## 3. WHY (b) BEATS (a), STATED AS A DECISION

1. **Self-consistency.** The keeper takes the claim sid from `sup-status --json`. Resolved in that
   same call, the union is guaranteed to contain that sid or to be `null`. Resolved by the keeper
   from its own registry read, the two come from different processes at different instants, and a
   fork-steer landing between them yields a claim sid the union does not contain — the exact race
   the union exists to bridge.
2. **The keeper stays narrow.** MEASURED and pinned by
   `test_the_keeper_reads_no_registry_of_its_own_to_get_the_union`: its subprocess set is
   unchanged, the test's `home` has **no registry at all** while `collect` still produces a full
   observation, no argv names `fleet.json`, and both of fleet's registry readers are recorded and
   asserted unreached. That last clause had to be rebuilt after a mutant showed the first version
   of it was unsound — see M10 in §5, which is worth reading before trusting any other pin here.
3. **One resolver, one identity concept.** `supervisor_claim_sids` resolves through `_record_sids`,
   the same union `_caller_holds_supervisor_claim` uses. Two spellings of one identity concept is
   the defect class this repo keeps re-finding; the `_record_sids` enumeration comment now cites
   fifteen sites instead of fourteen, and `tests/test_self_citations.py` **forced** that update —
   it derives the call-site set from the source and went red until the new site was cited.
4. **It serves the human guard too.** The two-live-body guard is a procedure a PERSON runs, and the
   surface they type mid-incident is `fleet sup-status`, not `--json`. The human form now prints
   `same body, retired sids: …` when there are any, and prints nothing extra when there are not.

---

## 4. WHY C IS NOT TOUCHED, AND WHAT w61's 27/27 LOOKS LIKE OVER A FORKED BODY

**C fixed the false negative and inherited the false positive** — the brief's §2 is right, and
MEASURED: at `64aa96b`, driven on the 10:16Z observation, C pages with `claim session not in the
roster` (§1). C's arm is the membership predicate's VALUE (`status == "busy"`); w63 changes its
SUBJECT. Both are needed; neither replaces the other.

**w61's *"pid/status presence is a perfect live/dead discriminator, 27/27"* — re-derived over a
forked body, as the brief asked.** MEASURED 2026-09-10T10:38Z, 18 plain rows, `kill -0` on every
pid:

- **10 rows carried a `pid`; all 10 processes were alive.** 8 rows carried none and carried no
  `status` either. `pid` and `status` presence moved together on all 18. **So the discriminator
  itself survives contact with a forked body — 2/2 over the 4f99 body's own listed sids.**
- **But it answers the wrong question, and that is the finding.** The 4f99 body had **two live
  processes and two roster rows at once** — `37e5c61c…` idle at pid 434832 and `42445477…` busy at
  pid 515437. Both are `claude bg-spare` processes taken from the daemon's pre-warm pool, with
  **unrelated parents** (ppids 434816 and 515425) and elapsed times of `02:44:42` and `39:26` at
  the sample — so ~07:54Z and ~09:59Z starts (derived from `etime`, not read off a clock). A
  fork-steer does not re-enter the old process; it claims a NEW spare and leaves the old one
  alive and idle. A per-ROW discriminator cannot be wrong about a body it
  models as one row. **w61's figure is fine; the frame around it is what the fork breaks**, and
  the brief's instinct that 27/27 "cannot have included a forked body" is right for a reason it
  did not state: a forked body is not one row, so it is not one sample.

**Union membership is NOT liveness, and the mutant proves the code knows it.** MEASURED:
`sup|inc-20260910T041459Z-2382|boot` had **both** retired sids (`27e3e17d…`, `65602a07…`) in the
plain roster as pid-less `blocked` rows while its current `session_id` (`ed943460…`) had no plain
row at all. That body is dead and must page. It does: all-corpse unions grade `dead`
(`body listed with no live process`). M2 — "any union row means live" — reddens five pins (§5).

---

## 5. THE MUTANTS — ELEVEN, TWO OF WHICH FOUND UNSOUND PINS OF MINE

**MEASURED, re-run against the tip `1b76726`.** Every mutant was planted in
`$CLAUDE_JOB_DIR/tmp/mutant`, a separate `git clone --no-local` of the branch — never in this
worktree, never in the floor clone — and reverted with `git checkout --` before the next. The
battery runs the five keeper test files plus the new one (156 tests); **all eleven go RED and none
is redundant** — no two mutants redden the same set. Two of them were caught by the harness itself:
M7's and M8's anchors stopped matching when later commits touched those lines, and the script
**fails loudly on a non-unique anchor** rather than reporting a green mutant, which is the only
reason this table is not quietly two rows short.

| # | mutation | reddens |
|---|---|---|
| **M1** | the join reverts to the **bare claim sid** (C's predicate) | **3**, incl. `test_the_10_16Z_false_page_does_not_fire_end_to_end` and `test_the_pre_steer_row_is_what_the_join_finds` |
| **M2** | **any union row means live**, regardless of `status`/`pid` | 5, incl. `test_a_body_whose_whole_union_is_corpses_still_pages` |
| M3 | drop the union members' type normalisation | 1 — `test_a_malformed_claim_sids_can_never_kill_the_tick` |
| M4 | resolve the holder by `rec["session_id"] == holder` instead of `_record_sids` | 1 — the ND4a stale-claim window |
| M5 | pool EVERY record's sids into one union | 1 — `test_another_bodys_record_never_contributes_its_sids` |
| M6 | read the registry with `load_registry` | 2, incl. the non-quarantine pin |
| M7 | drop the `under a retired sid` clause | 2 — the 10:16Z reason clause, both pins |
| M8 | publish `claim_sids: null` unconditionally | 2 — the JSON and the human form |
| M9 | drop the claim-sid-known guard on the retired-sid clause | 1 — `test_a_live_row_is_not_called_retired_when_the_claim_sid_is_unknown` |
| **M10** | **the keeper resolves the union itself — option (a)** | 2 — the narrow-reader pin, once it was sound |
| **M11** | **the resolver takes `fleet.lock`** | 1 — the view pin, once it was sound |

### M10 and M11 — the mutants that proved three pins of mine were worthless

This is the most useful paragraph in the report, and it is about my own work being wrong.

I claimed in §3 that the keeper reads no registry of its own, and in §2 that the resolver takes no
lock and is not `load_registry`. I pinned all three. **M10 is the keeper the brief's option (a)
would have produced** — `collect` resolving the union itself — and **M11 wraps the resolver's
registry read in `fleet_lock()`**. Both were planted precisely to check that those pins fire.
MEASURED, in order:

1. All three pins were written as monkeypatched stubs calling `pytest.fail(...)`. **M10 passed all
   48 tests.** `pytest.fail` raises `Failed`, which derives from `Exception`, and
   `supervisor_claim_sids` — like every reader on a view path in this repo — ends in
   `except Exception: return None`. **The mutant swallowed the pin's own failure.** A pin that the
   code under test can eat is not a pin. M11's target had the identical shape.
2. Rewritten to RECORD the call, delegate to the real function, and assert nothing was recorded —
   `cc7f59a` for the keeper pin, `81fa544` for the two resolver pins.
3. Re-run. **The pins go RED**:
   `FAILED …::test_the_keeper_reads_no_registry_of_its_own_to_get_the_union` under M10 and
   `FAILED …::test_the_union_read_never_takes_the_lock` under M11.

One honest sub-note, because it is the reason this took two attempts: the FIRST M10 I planted also
passed, and that green was **correct**. It called `supervisor_claim_sids()` with no argument, so
`read_incarnation()` returned `None` in the tmp home and the function short-circuited before
touching the registry at all. The seed was weak, not the code. The second variant passes the claim
through, which is what a real option-(a) keeper would do.

**The lesson generalises past this lane: any pin implemented by raising inside a function the
system under test wraps in `except Exception` is silently dead.** This repo has a great many
`except Exception: return None` view paths, each of them there for a good reason, and each of them
a place where this class of dead pin can live. I did not audit the others.

M1 and M2 are the two the brief names. **M1's verbatim output** (MEASURED):

```
E       AssertionError: KEEPER: supervisor stalled since 61 min ago (heartbeat 61 min stale,
        no session of this body in the roster). Report state, then relaunch with sup-spawn;
        do not await the operator.
E       assert 'roster says idle under a retired sid' in '…'
```

**One honest note about where M1 bites.** M1 does **not** redden the rules-level pin
`test_the_4f99_observation_never_pages_that_the_session_is_gone`, and it cannot: the join lives in
`collect`, so a rules-level fixture that hands `evaluate` a pre-built `claim_rows` is blind to it.
That is why `test_the_10_16Z_false_page_does_not_fire_end_to_end` exists — it runs
`collect` → `evaluate` → the page text on the event's real JSON, and it is the pin the brief's
pin 1 actually asks for. The rules-level twin pins the reason CLAUSE (M7 reddens that one).

---

## 6. THE PINS FROM BOTH EVENTS

**Pin 1 — the 10:16Z false page must not fire.** `test_the_10_16Z_false_page_does_not_fire_end_to_
end` (collect→evaluate→text) and `test_the_4f99_observation_never_pages_that_the_session_is_gone`
(the clause). The body pages `supervisor-stalled` **for idleness**, which is what C says and is
correct; what it must never say is that the session is gone. Pinned in both directions:
`"roster says idle under a retired sid" in text` and `"not in the roster" not in text`,
`"no live process" not in text`, `"dead" not in text`.

**Pin 2 — yesterday's true stall must still page.** The two pre-existing efa0 replays
(`test_the_efa0_observation_pages_at_the_first_stale_tick` and
`…_still_pages_seven_hours_later`, plus the mechanical pre-C reconstruction) are green under the
union — I migrated their fixtures to `claim_rows` rather than leaving them on keys the code no
longer reads, so they still measure the outage and not a dead shape. On top of them,
`test_the_efa0_stall_still_pages_once_the_body_has_a_union` gives efa0's body a union it never had
(its own row idle + a retired corpse) and asserts the page still lands at the first stale tick,
still on `roster says idle`, and **without** the retired-sid clause — because efa0's live row is
its own.

**The corrected arithmetic is used, not the old figure.** Detection moves earlier by **7h09m59s**
(w62-keeperc §8.2), not 7h10m51s; the page is recorded at `04:14:35.385Z` while the journal tick
says `04:14:36Z`. The fixture constant is `3652.0` — the real beat age at
**2026-09-09T21:04:36Z** — and not a round number chosen to make a test pass. **I did not re-derive
these from the daemon log**; they are w61's and w62-keeperc's MEASURED inputs, carried forward
(BELIEVED at this lane's remove).

---

## 7. THE INTERFACE GUARD — AMENDED, NOT REVERTED

`w62-keeperc` rewrote this file (the `supervisor-stalled` rename and the new step-3 bullet). I read
its diff first (`git log -p -2 -- docs/operator/server-interface-profile.md`) and every one of its
sentences survives.

**Step 2 was wrong in BOTH directions, and the brief only named one of them.** The brief says the
old rule missed live fork-steered bodies and so authorises a second body. True. But the same
sentence — *"a claim's `session_id` still listed there is a **live body**; do not dispatch"* —
also **makes a corpse immortal**: a dead session's row persists with `status` and `pid` absent
(w61 measured five at once, one 22h old, no expiry), so "still listed" blocks every revival of a
body that is genuinely gone. **MEASURED on this host today**, `sup|inc-20260910T041459Z-2382|boot`
is exactly that body. The interface's own formulation, which the brief quotes and I landed
verbatim, already carries the fix — *"…has a roster row **with a `pid`**"* — but the brief's §3(b)
prose names only the union half. **A lane that landed the union without the `pid` half would have
traded a false page for a permanent refusal to revive.**

Also landed: step 1 now reads on the union (and names where to find it), the step-3 "live, idle
supervisor" bullet is widened from `session_id` to the union, and the page's reason-clause list is
updated with the three new clauses plus a THIRD consequence bullet explaining
`sid union unavailable` as an **ambiguous** state — page the operator, do not dispatch.

---

## 8. WHAT THE SUITE MADE ME DO THAT THE BRIEF DID NOT MENTION

Inserting 66 lines into `bin/fleet.py` **broke 7 tests in `tests/test_self_citations.py` and 2 in
`tests/test_retired_sid_citations.py`** — the file explains itself with bare line numbers and they
rot on any edit above them. MEASURED (re-derived from the base blob and the final tree, not from
the fixer's own log): the file carried **43** self-citations at `64aa96b` and carries **44** now;
**39 of the 43 were re-pointed**, mechanically, by mapping old→new line numbers with `difflib` over
the base blob and rewriting only citations sitting on lines unchanged from base. Two more had to be
done by hand:

- the RANGE END of `` `cmd_respawn:9223-9225` `` — the end has no colon, so no `:NNNN` scanner sees
  it. **`test_every_ranged_citation_END_resolves_in_the_same_function` caught it**, exactly the B1
  guard `w45-gceil` §2 filed it for. Re-pointed to `9286-9288` and verified line-for-line against
  the base blob.
- the `_record_sids` **enumeration**, which is compared against a set derived from the source and
  went red naming the missing line (`:2896`) — my own new call site. Fourteen → fifteen, with the
  fifteenth named in prose.

That is **40 changed numbers in one lane** (39 re-pointed, 1 added, 1 range end), and a reviewer
should read them as **mechanically derived, not hand-typed**: the mapping came from `difflib` over
the base blob, and every one of them is re-checked by a test that resolves it against the source.
This is the harness working, not incidental churn.

---

## 9. WHERE THIS BRIEF WAS WRONG

1. **§4's framing of the read as a D4 question.** It is not one. D4 forbids lock/probe/write/
   quarantine; a read-only registry read is none of those, `status_snapshot()` already does it, and
   `_registry_records_or_none` exists precisely so a non-lock-holding reader can do it safely.
   **No gate is owed**, and the brief pre-authorised a gate draft for a collision that does not
   exist. The REAL obstacle was narrower and more interesting: **nothing the keeper reads publishes
   a session id at all except `sup-status`**, so there was no join key to widen in the first place.
2. **§3(b) names only half of what step 2 got wrong.** Its "listed = live" sentence also keeps dead
   bodies alive forever (§7). The brief's quoted formulation has the `pid` half; its narrative does
   not, and a lane following the narrative would have shipped a guard that never revives anything.
3. **"A fork's roster row exists only while its turn runs (`done` rows drop)" is right about the
   event and wrong as a general rule.** MEASURED 2026-09-10T10:56Z: the PLAIN spelling contained
   **three `state: "done"` rows**, each with a live pid and `status: "idle"`. Every one of the 14
   rows `--all` added was terminal-state **AND pid-less** (key set exactly
   `['cwd','id','kind','name','sessionId','startedAt','state']`). **The omission is keyed on the
   PROCESS being gone, not on the state word.** The same measurement confirms the mechanism on the
   very body in question: `d605e989…` (an earlier fork of 4f99) was `--all`-only while its two
   sibling sids were in the plain list. `bin/fleet_keeper.py`'s `_agents` docstring said the flat
   version; it now says the measured one (`c41e451`).
4. **The brief's §2 note on w61's 27/27 is right for a reason it does not give.** The discriminator
   is fine over a forked body (2/2, and 10/10 across the whole roster); what breaks is the
   assumption that one body is one row. See §4.
5. **§5's "at `2026-09-09T21:04:36Z` (not `04:14:36Z`)" is correct and I used it**, together with
   w62-keeperc's corrected 7h09m59s. No further correction found. *(BELIEVED at this remove — I did
   not re-open `journalctl`.)*

**Where the brief was right and I confirmed it independently:** the defect, the mechanism, the
steady-state framing, and the choice of `sup-status` as the cheapest correct site.

---

## 10. THE RESIDUAL, AND WHAT IS OWED

**A page that says `relaunch with sup-spawn` about a body the guard will REFUSE to relaunch.**
The 10:16Z shape now pages `supervisor stalled … roster says idle under a retired sid … Report
state, then relaunch with sup-spawn; do not await the operator` — and
`server-interface-profile.md` consequence 2 tells the interface **not** to dispatch over a live
idle body. **The page's instruction and the guard's rule disagree, on the most common stall shape
there is.** This is C's inheritance, not w63's: the instruction text is fixed by the 2026-09-09
operator amendment (*"keeper must just instruct interface to relaunch supervisor"*), and neither
the amendment nor G-K6 anticipated a page about a body that is alive. **I did not change it** — the
sentence is an operator ruling's own words and the fix is a ruling, not a lane's edit.

**GATE DRAFT (I file no gates; this comes to the supervisor):**

> **G-K8? — the `supervisor-stalled` page instructs a relaunch the guard refuses.**
> The keeper's page ends `Report state, then relaunch with sup-spawn; do not await the operator`
> (2026-09-09 amendment). Since G-K6/C the same page also fires for a body that is **alive and
> idle**, and `docs/operator/server-interface-profile.md` correctly refuses to `sup-spawn` over
> one. On this host that is the COMMON shape, not the rare one. Options: (i) make the instruction
> conditional on the activity class — `relaunch` for `absent`/`dead`, `carry to the operator` for
> `quiet`; (ii) leave the page and rely on the interface's guard, accepting that the loudest line
> the operator sees is wrong about the remedy; (iii) build G-K6 wave 2 (the wake mechanism) so the
> `quiet` class stops occurring. **The keeper CAN tell the classes apart already** — `_claim_activity`
> returns the class — so (i) is a small change, but the page text is an operator ruling's own words.

**Doc drift the merge owes (NOT fixed here — §6 forbids spec edits):**
`docs/specs/graceful-succession.md` §R4 says *"`sup-status --json`'s **eight** keys"*. It is now
nine. **The RECEIPT is safe** — it is pinned `# at cebae4f` and is verified against that commit's
tree, so `tools/verify_receipts.py` cannot rot on my change (MEASURED: the receipt block carries
that sha). It is the surrounding present-tense PROSE that is now stale.

**NOT AUDITED, and named so nobody reads this lane as wider than it is.** `bin/fleet.py` has
~17 `_fetch_agents_roster` call sites. I did not audit them for the same bare-sid defect; the brief
named two sites and I built two. What I can say is where an auditor should start: the enumeration
comment at `bin/fleet.py:16174` now lists **fifteen** union-keyed identity sites and
`tests/test_self_citations.py` derives that set from the source, so a roster join that is NOT
union-keyed is precisely one that does not appear there. B6 (`_releaser_is_roster_live`) was the
last such site found, by councilor 1, and it took a wedge to find it.

**Unmeasured, and named: I never watched a turn END.** A bounded roster sampler ran
**10:38:58Z → 11:20:36Z, 42 samples at 60 s**, and the 4f99 body read `status: "busy"` at every
one of them, with a heartbeat ~45 min stale — the legitimate-long-turn case C suppresses on
purpose, live, for the whole of this lane. So I did not see the fork row drop in real time. Two
things I did see:

- **exactly one transition, at 11:18:35Z: the claim row's `state` moved `blocked` → `working`
  while `status` stayed `busy` and the pid did not move.** `state` and `status` are independent
  fields that move at different times; C's choice to arm on `status` (and w61's measurement behind
  it) is untouched by this, but it is worth knowing that `state` alone would have been a different
  and noisier signal.
- the drop itself, MEASURED **structurally** rather than temporally: `d605e989…` (a prior fork of
  this very body) and `ed943460…` are `--all`-only right now with the exact pid-less terminal
  shape, which is the same fact one turn later.

The keeper was never run against the live home, in any mode, `--dry-run` included.

**Considered and deliberately NOT changed: the dedup fingerprint.** It stays
`held:stale:<claim_sid>`, and `claim_sid` **rotates on every fork-steer** — so two stalls either
side of a `fleet send` dedup as different pages and the operator is paged twice. I judged that
correct (a steer is a fresh attempt to un-stall the body; a stall that survives it is news) and, in
any case, out of a join lane's fence: re-keying on the incarnation id or the union's minimum is a
behaviour change to `dedup` that no measured event asks for. Named in
`rule_supervisor_stalled`'s docstring so the next reader does not rediscover it. w62-keeperc §6
paid the one-off re-fire for the rename; this lane adds none.

---

## 11. EVERY COMMAND THAT TOUCHED A LIVE SURFACE

All read-only. MEASURED:

- `cat /home/altai/proga/fleet/supervisor/INCARNATION`; `state/fleet.json` read via python
  `json.load` (never `fleet.load_registry`, which quarantines)
- `claude agents --json` and `claude agents --json --all`, run from `/home/altai/proga/fleet`
- `kill -0 <pid>` and `ps -o pid,ppid,etime,args` on the 10 roster pids
- the bounded sampler `roster_sampler.sh` — `claude agents --json` only, 60 samples max, 60 s
  apart, self-terminating; pid 559200, output `$CLAUDE_JOB_DIR/tmp/roster-samples.jsonl`. Killed
  before this turn ended; its pid was in the journal from the moment it started.
- **`FLEET_HOME=/home/altai/proga/fleet python bin/fleet.py sup-status [--json]`, this branch's
  build, twice** (§1). `cmd_sup_status` is a view: `read_incarnation`, `read_handshake`,
  `supervisor_goals_active`, `read_pending_decision`, `_interface_divergence`,
  `supervisor_status_line`, and — new in w63 — `_registry_records_or_none`. No lock, no write, no
  probe. Checked afterwards: `state/` contains no `fleet.lock` and no `fleet.json.corrupt.*`.

**Nothing wrote to the live home. No `fleet` mutating verb was run. `bin/fleet_keeper.py` was never
executed against the live home, in any mode, `--dry-run` included. The suite was never run in the
main checkout** — the floor ran in `$CLAUDE_JOB_DIR/tmp/floor`, the branch in `…/branch` and
`…/final`/`…/final312`, the mutants in `…/mutant`, each a separate `git clone --no-local`.

---

## 12. SUITE FLOOR

**PREDICTED IN WRITING FIRST** (journal, 2026-09-10T10:39Z, before any run): 4978 collected,
`6 failed, 4955 passed, 16 skipped, 1 xfailed`, identical on 3.10 and 3.12; and after the change,
collected rises by exactly the tests added with the same six ids.

MEASURED, `uv run --no-project --python 3.1x --with pytest python -m pytest -q --color=no`, each
in its own `git clone --no-local`:

| tree | py | result | collected | wall |
|---|---|---|---|---|
| `64aa96b` FLOOR | 3.12 | `6 failed, 4955 passed, 16 skipped, 1 xfailed` | 4978 | 337.38 s |
| `64aa96b` FLOOR | 3.10 | `6 failed, 4955 passed, 16 skipped, 1 xfailed` | 4978 | 436.83 s |
| `c41e451` | 3.12 | `6 failed, 4987 passed, 16 skipped, 1 xfailed` | 5010 | 343.79 s |
| `338fc86` | 3.12 | `6 failed, 4987 passed, 16 skipped, 1 xfailed` | 5010 | 425.12 s |
| `338fc86` | 3.10 | `6 failed, 4987 passed, 16 skipped, 1 xfailed` | 5010 | 490.50 s |
| `1b76726` | 3.12 | `6 failed, 4988 passed, 16 skipped, 1 xfailed` | 5011 | 370.86 s |
| `1b76726` | 3.10 | `6 failed, 4988 passed, 16 skipped, 1 xfailed` | 5011 | 404.85 s |
| `cc7f59a` | 3.12 | `6 failed, 4988 passed, 16 skipped, 1 xfailed` | 5011 | 397.53 s |
| `cc7f59a` | 3.10 | `6 failed, 4988 passed, 16 skipped, 1 xfailed` | 5011 | 450.13 s |
| **`81fa544`** | 3.12 | `6 failed, 4988 passed, 16 skipped, 1 xfailed` | 5011 | 504.40 s |
| **`81fa544`** | 3.10 | `6 failed, 4988 passed, 16 skipped, 1 xfailed` | 5011 | 554.80 s |

**The tip of the branch is `3e7f448`, one commit past `81fa544`, and it is MARKDOWN ONLY** — one
sentence in `docs/operator/server-interface-profile.md`, a file no test reads (`test_keeper_main`
writes its own fixture copy of that path). I did not re-run the whole suite for it; I re-ran the
five doc-scanning suites (`test_doc_claims`, `test_receipts`, `test_doctrine_citations`,
`test_lane_report_durability`, `test_keeper_main`) — **187 passed** — and the two later wall-clock
figures above are inflated by the two interpreters sharing this 8 GB host, not by anything the
branch does.

**Four predictions, all held, all written down before their run.** (1) The floor, from the brief:
4978 / `6 failed, 4955 passed, 16 skipped, 1 xfailed`, identical on both — exact, on both.
(2) The branch, written into the journal before that run finished: +32 tests → 5010 /
`…4987 passed…` — exact, on both. (3) `1b76726`: one more test → 5011 — exact, on both.
(4) `cc7f59a`/`81fa544`: test-only commits that add no test → 5011 — exact, on both.

**Every failure SET is byte-identical** — floor 3.10↔3.12, tip 3.10↔3.12, and floor↔tip (MEASURED:
`diff` of the sorted `FAILED` lines is empty in all three comparisons). All six are the known host
assumptions: four Windows drive-qualified-path escapes in
`test_fleet_index.py`/`test_fleet_q.py`, two venv-shim re-execs in `test_terminal_surface.py`.
**No `skipif` added, none removed; skips and the one xfail are unmoved.**
