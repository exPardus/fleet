# w62-keeperc — G-K6 wave 1 (C): the supervisor alarm now arms on `status == "busy"`

**Lane:** build (keeper). Branch `w62/keeper-c` from `374929b`; the change is `c6b6713`.
**Every line below is tagged MEASURED (I ran it, on this host, today, 2026-09-10) or BELIEVED
(inference, code reading, or someone else's report).** Host `kz-work`, Linux 6.8.0-139.

**Scope built: C only.** No wake mechanism (B) — no waker, no timer, no self-scheduling turn.
`bin/fleet.py` is untouched (MEASURED: `git diff --stat 374929b..c6b6713 -- bin/fleet.py` is empty;
its `--all` roster call still reads `run([exe, "agents", "--json", "--all"], …)` at
`bin/fleet.py:16307`). The keeper was never run against the live home, in any mode, `--dry-run`
included (§9).

---

## 1. WHAT CHANGED, IN ONE PAIR OF LINES

```
-        if obs.get("claim_sid_live"):
+        activity, status = _claim_activity(obs)
+        if activity == "busy":
             return None
```

The suppressor was "the claim's session id appears in `claude agents --json`". It is now "the
claim's own row in `claude agents --json` reads `status == "busy"`". **The sid join is untouched —
only the membership predicate changed** (§4).

MEASURED, `git diff --numstat 374929b..c6b6713` — 7 files, 524 insertions, 132 deletions:
`bin/fleet_keeper.py` +184/−41, `tests/test_keeper_rules.py` +229/−54,
`tests/test_keeper_collect.py` +80/−15, `tests/test_keeper_main.py` +14/−14,
`docs/operator/server-interface-profile.md` +10/−2 (§7), `tests/test_keeper_dedup.py` +6/−5,
`tests/test_sup_notify.py` +1/−1. No other file moved. Most of the keeper's +184 is docstring: the
arming itself is the four lines above plus `_claim_activity`.

### The three-way read the keeper never had

`_agents` returned a `set` of sids and threw the row away. It now returns `{sessionId: status}`,
and `_claim_activity(obs)` classifies the claim's own row **four** ways:

| class | roster shape | pages when the beat is stale? | reason clause in the page |
|---|---|---|---|
| `busy` | listed, `status == "busy"` | **no** | — |
| `quiet` | listed, any other non-empty string status | **yes** | `roster says idle` (or `waiting`, …) |
| `dead` | listed, **no `status` key at all** | **yes** | `claim session listed with no live process` |
| `absent` | no row for this sid | **yes** | `claim session not in the roster` |

**MEASURED (w61 §2, re-derived from that report's own row dumps, not re-run here): on a dead row
`status` and `pid` are ABSENT from the object, not present-and-null.** So `row["status"]` would
raise straight out of the tick and **fail the alarm CLOSED** — the worst available direction. The
mutant M4 (§5) is exactly that line, and it dies.

**`busy` is an ALLOWLIST OF ONE, and that is the deliberate part.** `idle`, `waiting`, a value a
later CLI invents, a non-string, an absent key — all read as *not working* and all page. A
denylist ("page unless the status is one of these dead ones") would silently re-acquire the
2026-09-09 blindness the first time the CLI shipped a new value. MEASURED: mutant M3 turns the
allowlist into a denylist and `test_an_unrecognised_status_value_pages_rather_than_suppressing`
goes red.

**A missing obs key is handled explicitly, not by `.get()` accident.** `_claim_activity({})`
returns `("absent", None)` — MEASURED, pinned by
`test_the_activity_classifier_is_four_ways_and_each_way_is_reachable` and by
`test_a_missing_roster_key_is_handled_deliberately_not_by_accident`, which builds an observation
carrying **neither** roster key and asserts the rule still pages.

---

## 2. THE efa0 REPLAY — THE PIN THAT IS THE WHOLE POINT

MEASURED, driven as pure functions (`k.evaluate` on hand-built observation dicts; the keeper binary
was never executed):

| observation | pre-C | post-C |
|---|---|---|
| efa0 at the first stale tick (`held`, beat `3652.0`, sid listed, `status: "idle"`) | **`[]`** | **`["supervisor-stalled"]`** |
| efa0 seven hours later (same, beat `29451.0`) | `[]` | `["supervisor-stalled"]`, same fingerprint |
| a busy supervisor mid-long-turn, beat `29451.0`, `status: "busy"` | `[]` | **`[]`** |
| a dead row: listed, no `status` key, beat stale | `[]` | `["supervisor-stalled"]` |

The positive direction is `test_the_efa0_observation_pages_at_the_first_stale_tick`. The negative
direction — that the pre-C code was silent on the *identical* observation — is
`test_the_pre_c_arm_would_have_been_silent_on_the_same_observation`, which **reconstructs the old
predicate mechanically from the same obs dict** (`claim_sid is not None and claim_in_roster`)
rather than asserting it from memory, and it is also what mutant M1 proves by putting the old arm
back on disk.

Under M1, that pin printed, verbatim (MEASURED):

```
E       AssertionError: the 2026-09-09 outage observation must PAGE at 21:04:36Z
E       assert [] == ['supervisor-stalled']
```

**The empty list is the outage.** Every silent tick across those eight hours was a rule returning
exactly that, exactly as written.

### The arithmetic, re-derived — and w61 §7's headline number is off by 52 seconds

MEASURED (`datetime`, from w61's own MEASURED inputs; `state/keeper/last-page.json`'s recorded
epoch `1789013675.385` resolves to `2026-09-10T04:14:35.385Z`, confirming w61's reading):

| quantity | value |
|---|---|
| last supervisor heartbeat | `2026-09-09T20:03:44Z` |
| heartbeat crosses `HEARTBEAT_STALE_SECONDS` (3600) | `2026-09-09T21:03:44Z` |
| first keeper tick at or after that (w61, `journalctl`) | `2026-09-09T21:04:36Z` |
| page actually sent | `2026-09-10T04:14:35Z` |
| **dark window as it happened** (beat → page) | **8h10m51s** |
| **dark window under C** (beat → the tick that now pages) | **1h00m52s** |
| **detection moves earlier by** | **7h09m59s** |

**`7h10m51s`, the figure in `docs/lanes/w61-keeperblind.md` §0/§7 and repeated verbatim in
`docs/OPERATOR-GATES.md` G-K6 item 3, is wrong by 52 s**: it is the *dark window's* minutes and
seconds (`10m51s`) pasted onto the hours of a different subtraction. The correct value is
**7h09m59s** (7h10m00s if you take the journal's `04:14:36Z` rather than the state file's
`04:14:35Z`). Nothing decision-relevant turns on it and the ruling is unaffected — recorded because
it is a number sitting in an open operator gate, and the next person to check it will find the
same discrepancy and wonder which half rotted.

The constant `3652.0` in the test file is that `1h00m52s`, so the fixture is the observation the
keeper would really have built at 21:04:36Z, not a round number chosen to make a test pass.

---

## 3. THE RESIDUAL, STATED PLAINLY

**A supervisor WEDGED MID-TURN reports `status: "busy"` for as long as its process lives, and this
rule stays silent for exactly as long.** UNMEASURED — w61 could not produce a wedge and neither did
this lane; I did not attempt one, because producing a genuinely wedged Claude session is not
something I can do reliably and a faked one would prove nothing about the real shape.

It is written into `rule_supervisor_stalled`'s docstring in those words, not only here.

Two honest qualifications:

- **It is strictly smaller than the hole it replaces.** The old arm swallowed *every* listed body —
  wedged, idle, and long-dead alike (MEASURED by w61: 5 of 10 plain rows were corpses, one listed
  for 22h05m). C swallows only the wedged-busy one.
- **It is the standing argument for reading A.** A heartbeat-only rule would catch the wedge too.
  C is A minus that catch, plus C2's guard against paging at a healthy fleet. The operator chose C;
  this lane is not re-opening it, only naming what C does not cover so wave 2 (B) and any future A
  argument start from the true perimeter.

**A supervisor mid-LEGITIMATE-long-turn reads `busy` too and is suppressed on purpose** — that is
C's whole claim to introducing no new false positive, and it is pinned across three beat values
(`3601`, `29451`, `108000`) by
`test_a_busy_supervisor_mid_long_turn_with_a_stale_beat_is_suppressed`.

---

## 4. THE SID JOIN STAYED, AND WHY THAT MATTERED TO THE IMPLEMENTATION

C2's fix — join on the claim's **session id**, never a `sup|` name prefix — is untouched, because
`ai-title` can overwrite `name` after a resume, so a name join can bind a live supervisor to the
wrong row or miss it and page at a healthy fleet. MEASURED: `test_the_claim_session_is_looked_up_by
_sid_not_by_name` and `test_a_supervisor_shaped_name_from_another_launch_is_not_the_claim` are
unchanged in intent and green.

**One inherited hazard survived the refactor and had to be kept alive deliberately.** Re-review
minor 2 normalises a non-`str` `session_id` *before* the roster test, because a dict reaching
`claim_sid in agent_sids` raised `TypeError` out of the tick (`in` on a set hashes its operand).
C swapped that set for a dict — **and a dict key lookup hashes its operand exactly the same way**,
so the normalisation is still the only thing between a malformed `sup-status` projection and a dead
tick. `test_a_non_string_session_id_is_normalised_before_the_roster_test` keeps its teeth and its
docstring now says why it still applies.

Symmetrically, the roster row's own `status` is normalised on the way in: a non-`str` or empty
value becomes `None`, i.e. the corpse reading, so a malformed row can never *silence* the alarm
(`test_a_non_string_status_on_the_claim_row_is_not_a_working_body`, five shapes).

**Spelling discipline.** The keeper calls `claude agents --json`, **no `--all`**; `bin/fleet.py`
uses `--all`. They are different lists. `test_the_keeper_asks_the_plain_spelling_and_never_all` now
pins the exact argv the keeper sends, so the two surfaces cannot be silently merged.

---

## 5. THE MUTANTS — WHICH ONES, AND WHAT THEY PRINTED

**MEASURED.** Six mutants, each planted in a **separate `git clone --no-local`**
(`$CLAUDE_JOB_DIR/tmp/mutant`), never in this worktree and never in the floor clone.

The driver (`$CLAUDE_JOB_DIR/tmp/plant.py`, outside the repo) **proves its own patch landed before
it runs one test**, because a refusing planter plus a clean floor reads exactly like a surviving
mutant. Four assertions, all before pytest is invoked: the anchor must appear **exactly once**; the
file must actually differ after the write; the replacement must be readable back **from disk**; and
`git diff --stat` must name the file. Afterwards it reverts and re-checks `git status --porcelain`.

**Both refusal paths were exercised, not merely written** (MEASURED):

```
ABORT: tree is dirty before planting:
 M bin/fleet_keeper.py
ABORT: anchor for M3-denylist-not-allowlist found 0 times, expected 1 -- the planter did not
       apply and a green run would be a lie
```

Neither reached pytest (rc 1, no summary line). **No floor run was started with a mutant on disk**:
the mutant clone was `git reset --hard c6b6713` and verified `git status --porcelain`-empty, and
the floor runs happened in a *different* clone that was never written to at all.

| mutant | the reversion | RED |
|---|---|---|
| **M1** `pre-c-presence-arm` | `if activity == "busy"` → `if activity != "absent"` — the **exact** pre-C predicate | **9** |
| **M2** `idle-counts-as-working` | → `if activity in ("busy", "quiet")` — reads the status but calls idle "working" | **7** |
| **M3** `denylist-not-allowlist` | `("busy" if status == ROSTER_BUSY else "quiet")` → `("quiet" if status == "idle" else "busy")` | **1** |
| **M4** `subscript-a-missing-status` | `row.get("status")` → `row["status"]` — the alarm fails CLOSED | **1** |
| **M5** `beat-in-the-fingerprint` | appends `:{beat}` to the held+stale `fp` | **3** |
| **M6** `page-still-says-dead` | reverts the page head to `supervisor dead` | **8** |

M1's nine, in full (the set that would have to go green again for the outage to return):

```
tests/test_keeper_collect.py::test_a_dead_row_keeps_its_sid_and_carries_no_status_key
tests/test_keeper_collect.py::test_the_claim_rows_status_reaches_the_observation
tests/test_keeper_dedup.py::test_a_held_stale_supervisor_stalled_page_dedups_across_a_tick
tests/test_keeper_rules.py::test_a_dead_row_carrying_no_status_key_pages
tests/test_keeper_rules.py::test_an_unrecognised_status_value_pages_rather_than_suppressing
tests/test_keeper_rules.py::test_the_efa0_observation_pages_at_the_first_stale_tick
tests/test_keeper_rules.py::test_the_efa0_observation_still_pages_seven_hours_later
tests/test_keeper_rules.py::test_the_fingerprint_does_not_carry_the_activity_class_either
tests/test_keeper_rules.py::test_the_pre_c_arm_would_have_been_silent_on_the_same_observation
```

Summary lines, MEASURED: M1 `9 failed, 106 passed`; M2 `7 failed, 108 passed`; M3 `1 failed, 114
passed`; M4 `1 failed, 114 passed`; M5 `3 failed, 112 passed`; M6 `8 failed, 107 passed`.

**M3 and M4 each kill exactly one pin, and that is the finding, not an omission.** They are the two
failure modes with no second witness: if either of those single tests is ever deleted or weakened,
that half of C is unguarded and nothing else will say so.

---

## 6. `fp` — THE INVARIANT RE-CHECKED, BECAUSE THE PAGE TEXT DID CHANGE

**The fingerprint still carries no heartbeat age.** MEASURED:
`test_held_stale_fingerprint_is_beat_free_across_ticks` (two ticks 900 s apart, same `fp`,
different text) and, end to end through `dedup`,
`test_a_held_stale_supervisor_stalled_page_dedups_across_a_tick`. M5 kills both plus one more. The
reason is unchanged and worth restating because it is the invariant an alarm change is most likely
to break: an age-bearing fingerprint never equals its predecessor, `dedup` can therefore never
suppress, and the operator is paged every 15 minutes instead of once per `REPAGE_SECONDS`.

**The reason clause DID change** (it now names the roster status), so the invariant was re-checked
rather than assumed — and one new decision was taken with it:

**The activity class is deliberately NOT in the fingerprint.** A stalled body degrades over time —
efa0 read `idle` for 8h10m and then, when the daemon retired it at `04:05:58Z`, became a row with
no `status` at all. Same claim, same stall, same remedy. A class-bearing fingerprint would re-page
on that transition. MEASURED and pinned by
`test_the_fingerprint_does_not_carry_the_activity_class_either`, which asserts the three classes
share one fingerprint, that the operator still sees the difference **in the text**, and that
`dedup` really does suppress the second one.

### The one cost of the rename, stated rather than discovered

`Page`'s rule name is the dedup key (`state/keeper/last-page.json` keys on it, and
`docs/operator/keeper-soak-2026-09.md` shows the file shape). Renaming `supervisor-dead` →
`supervisor-stalled` therefore **changes the dedup identity**: on the first tick after this lands,
any leftover `supervisor-dead` key is simply dropped (`dedup` forgets rules that stop firing) and
`supervisor-stalled` is treated as new, so **an in-flight page re-fires exactly once**. Acceptable;
it is the price of the alarm not lying, and it is bounded at one page.

**And right now that price is zero.** MEASURED, read-only `cat` of
`/home/altai/proga/fleet/state/keeper/last-page.json` at 2026-09-10 — the live file is:

```json
{
 "_hook_error_lines": 0
}
```

**There is no `supervisor-dead` entry in it.** The brief said there is (§8). The 04:14:35Z page's
key was dropped on the first tick after the supervisor came back, exactly as
`test_a_rule_that_stops_firing_is_forgotten` says it should be. **The file was not edited.**

---

## 7. THE INTERFACE PROFILE HAD TO MOVE WITH THE RULE — AND THE GUARD WILL NOW REFUSE

`docs/operator/server-interface-profile.md` identified the alarm as *"The `supervisor-dead` page —
the one that says the supervisor is dead or released"*. A page that says **stalled** is neither.
**Without this edit the interface would not have recognised its own alarm**, which is a worse
outcome than the bug being fixed. The bullet is rewritten, and the stale `2a15dec` "the shipped page
still says `await operator`" caveat — false since that text landed — is marked discharged.

**The larger finding, and it is the one the operator should read: the two-live-body guard has the
same defect the keeper rule just had, and fixing it is NOT in this wave's scope.**

MEASURED (profile text, steps 1–2): the guard dispatches only on `released`/`none`, or on a `held`
claim *"whose `session_id` is absent from the roster"*, and *"A claim's `session_id` still listed
there is a **live body**; do not dispatch."* — **presence, not status.** So on the exact 2026-09-09
shape, C's new page fires at 21:04:36Z and **the guard correctly refuses to `sup-spawn`**, because
the body genuinely is alive.

That is not a defect in C and I did not "fix" it, because it is not obviously wrong: dispatching a
second supervisor over a live idle one is precisely the two-live-body hazard the claim system
exists to prevent, and the idle body could still wake. So the profile now names the state
explicitly in its ambiguous list and tells the interface what to do: **page the operator**, say the
body is alive, quote the heartbeat age, and name the two mutating options (give it a turn with
`fleet send`, or retire and relaunch) as the operator's call, not the interface's.

**Net effect of C alone, stated honestly: detection moves from 8h10m51s to ~1h01m; the REMEDY on
the idle-body case becomes an operator page rather than an automatic relaunch.** That is still an
enormous improvement over eight hours of silence, and it is not the auto-revival the 2026-09-09
amendment set up for the *dead-body* case, which is unchanged and still auto-relaunches. **The
thing that closes the gap properly is G-K6 wave 2 (B)** — a wake mechanism means the body never
sits idle at all. **C is B's watchdog; B is what makes C's page rare.**

### G-K1 collision check (asked for by the brief)

**None found.** G-K1 makes the keeper an off-by-default feature flag. C adds no new always-on
surface, no new file, no new unit, no new state key that outlives a tick — it changes one predicate
and two observation keys inside a tick that the flag lane will gate wholesale. One note for that
lane, not a collision: **a disable/enable cycle across this rename leaves a stale `supervisor-dead`
key in `last-page.json`, which `dedup` drops harmlessly on the next tick.** Nothing to build for it;
worth not being surprised by.

---

## 8. WHERE THIS BRIEF WAS WRONG

Ordered by how much it would have cost a reader who trusted it.

1. **"`state/keeper/last-page.json` on the live host currently holds a `supervisor-dead` entry —
   do not edit the live file."** **MEASURED FALSE as to the entry** (§6): read-only, the file holds
   only `{"_hook_error_lines": 0}`. The key was dropped when the rule stopped firing after the
   04:15Z revival. **The instruction not to edit it is right and was obeyed** — but the fact it
   rests on is stale, and it matters because the brief uses that entry to price the rename. The
   real price of the rename **today** is zero pages; the once-only re-fire only applies if a stall
   is live at merge time. A reader who trusted the brief would have over-priced the rename and might
   have declined it for a cost that does not currently exist.
2. **"the page must land at `2026-09-09T21:04:36Z`, not `2026-09-10T04:14:36Z`"** — the *instruction*
   is right and is pinned. The **`04:14:36Z`** in it is the journal's tick timestamp; the page
   itself is recorded at **`04:14:35.385Z`** in `state/keeper/last-page.json`. One second, no
   consequence, recorded because the brief and the evidence base use the two interchangeably and
   the derived "7h10m51s" figure they both quote is wrong by 52 s (§2). The honest number is
   **7h09m59s**.
3. **"An idle or absent row pages once the heartbeat is stale."** Right, and **incomplete in the way
   that mattered to the implementation**: there is a third non-busy shape — **a row that is present
   and carries no `status` key at all**, which is what a dead-but-still-listed body looks like and
   which w61 measured five of. Treating it as "absent" would have produced a page whose reason
   clause said "not in the roster" about a sid that visibly *is* in the roster. It is its own class
   (`dead`) with its own sentence. The brief's own "HOW TO BE WRONG HERE" section is what pointed at
   it, so the two halves of the brief disagree slightly; the later half is the correct one.
4. **"Keep the sid join (that is C2's fix and it is load-bearing)."** Correct, obeyed, and the brief
   understates *why it is load-bearing in the code as well as in the design*: the type-normalisation
   that C2's re-review added to stop a `TypeError` killing the tick is still required after the set
   became a dict, for the same hashing reason (§4). A lane that "kept the sid join" but dropped the
   normalisation as set-specific would have reintroduced a tick-killing crash.
5. **"Rename honestly (`supervisor_stalled`) if the lane agrees the name is wrong. … an in-flight
   page could re-fire once."** Both correct and both acted on. What the brief does not say, and what
   nearly bit: **the rename forces a doc edit** in `docs/operator/server-interface-profile.md`,
   because the interface identifies the page by words the renamed page no longer says (§7). A lane
   that renamed and stopped would have shipped an alarm its only consumer could not recognise.
6. **"The measurement is already done — read it, do not redo it."** Excellent instruction, obeyed:
   `docs/lanes/w61-keeperblind.md` is thorough and I re-derived only what I depended on (the row
   shapes, the arming arithmetic, the daemon retirement disposition). Recorded so the next brief
   keeps it. The one place re-deriving paid: §2's 52-second arithmetic error.

---

## 9. EVERY COMMAND THAT TOUCHED A FLEET HOME OR A LIVE SURFACE

| what | target | write? |
|---|---|---|
| `cat state/keeper/last-page.json` | `/home/altai/proga/fleet` (live) | **read-only** |
| `k.evaluate(...)` / `k.collect(...)` on hand-built dicts | none | in-process, no fleet home |
| `pytest` (keeper files, then the full floor) | `$CLAUDE_JOB_DIR/tmp/{floor,base}` clones | their own tmp dirs only |
| mutant plant/revert | `$CLAUDE_JOB_DIR/tmp/mutant` clone | that clone's `bin/fleet_keeper.py`, reverted |

**Never run:** `bin/fleet_keeper.py` in any form, `--dry-run` included; any `fleet` verb against the
live home; anything that takes `fleet.lock`; `claude agents` (this lane needed no fresh roster —
w61's is the evidence base). **Never written:** `state/keeper/last-page.json`, the claim,
`supervisor/**`, the live registry, `state/events.jsonl`. **No page was sent, and no tmux window was
touched.** No process of mine is still running.

---

## 10. SUITE FLOOR

**Prediction, written before any suite run** (`state/journals/w62-keeperc.md`, at `c6b6713`):
**4978 collected, `6 failed, 4955 passed, 16 skipped, 1 xfailed`, identical on 3.10 and 3.12, same
six ids.** Derived as the brief's `374929b` baseline (4965) **+13**, counted by AST against that
commit: `tests/test_keeper_rules.py` 39 → 48, `tests/test_keeper_collect.py` 32 → 36. No
parametrized population moves — `tests/test_doc_claims.py` parametrizes over `current_tree_docs()`,
which excludes `docs/lanes/` by `_HISTORICAL_PREFIXES` (`tests/test_doc_claims.py:447`), so this
report adds no cases, and `docs/operator/server-interface-profile.md` was already tracked.

**MEASURED. Prediction held exactly, on both floors.** Each run from its own `git clone --no-local`
under `$CLAUDE_JOB_DIR/tmp`; **never from this worktree and never from the main checkout.**

**The baseline was re-measured rather than taken on trust**, in a third clone at `374929b`, because
the arithmetic alone could not distinguish "my +13 landed" from "my +13 landed and something else
silently vanished". It reproduces the brief's `374929b` figure exactly — `4942 + 6 + 16 + 1 =
4965` — so **4965 + 13 = 4978 is closed on both ends and every one of the 13 new cases is mine.**

| tree | commit | interpreter | result |
|---|---|---|---|
| `clone floor` | `c6b6713` (this lane) | 3.12 | `6 failed, 4955 passed, 16 skipped, 1 xfailed in 384.32s` |
| `clone floor` | `c6b6713` (this lane) | 3.10 | `6 failed, 4955 passed, 16 skipped, 1 xfailed in 555.30s` |
| `clone base` | `374929b` (baseline) | 3.12 | `6 failed, 4942 passed, 16 skipped, 1 xfailed in 358.90s` |

The six failures are the same six ids in every run, they are this host's assumptions and not fleet
defects, and none carries a `skipif`: three `test_fleet_index::TestPathContainment` +
one `test_fleet_q::TestOutlinePathContainment` (drive-qualified-path escapes) and two
`test_terminal_surface::TestCollaboratorInstall` (venv-shim re-execs).

Command, verbatim: `uv run --no-project --python 3.1x --with pytest python -m pytest -q --color=no`.

---

## 11. WHAT IS OWED, AND BY WHOM

Named, not done, because none of it is this lane's:

- **`docs/OPERATOR-GATES.md` G-K6** — the Settled line is the **operator's** to tick. Its item 3
  carries the `7h10m51s` figure corrected in §2 and the `claim_sid_live` spelling that no longer
  exists in the code; both are historical argument text and the file is `_HISTORICAL_PREFIXES`-exempt,
  so nothing reddens.
- **`docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md` §3.3** — its rules table
  still has a `supervisor-dead` row with the pre-amendment page text. Prose lane's; historical-prefix
  exempt.
- **`docs/SPEC.md` §18** — the server persistent-fleet entry names the `supervisor-dead` page.
  **Not exempt**, and it carries no check-count or verb claim that this change breaks (MEASURED: the
  full floor is green), but it is now describing a rule name that no longer ships.
- **`docs/operator/keeper-soak-2026-09.md`** — dated receipts of pages actually sent under the old
  name. **Leave them.** They are what the operator really saw.
- **G-K6 wave 2 (B)** — the wake mechanism, and §7's guard question that comes with it.
