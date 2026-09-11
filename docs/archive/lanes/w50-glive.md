# `w50-glive` — adversarial gate on `w50/live`, the liveness ruling

# VERDICT: **GATING**

| | |
|---|---|
| Under gate | `29cb116` on `w50/live` — `docs/lanes/w50-live.md` (672 lines) + `tests/test_liveness_readers.py` (20 tests) |
| Gate branch | `w50/glive`, branched at the same commit |
| `bin/fleet.py` | **byte-identical, verified both ways.** `git diff w50/live w50/glive` empty; sha256 `b76dc65d6007ba71e6c59dd47f6ac0502f92588466a22dfd1d1b5a2e4b50ef2c` before and after every mutant in this gate |
| Live fleet verbs run by this gate | **NONE.** Not `status`, not `peek`, not `result`, not `doctor`. §9 |
| Findings | **1 BLOCKING, 5 MAJOR, 5 MINOR** — and **10 CLEARED** (§5), which I record because the brief asked which parts it can rely on |

**I do not reject the branch outright.** The field-conflation diagnosis is sound,
the census is exact, and the ruling's core — *one canonical value, per-reader
policy* — survives every attack I ran. What gates is that the report's **headline
refutation is false**, and that five of its downstream sections, its proposed
replacement docstring, and one of its build mutants all descend from it. A
672-line specification a successor executes without re-deriving is exactly where
a false premise is most expensive, and this one is falsifiable in one command.

Every finding below is tagged **MEASURED** (I ran it and read the output) or
**BELIEVED** (reasoning over code I read but did not execute).

---

## 0. THE ONE THAT GATES

### F1 — BLOCKING — the headline refutation is falsified on the same machine, same day, same vendor

**MEASURED.** The report's §0, §3.1 and §7-row-2 rest on one number:

> *"137 live entries, 69 of them `done`, **zero** carrying `pid` or `status`."*
> *"§3.1 — The predecessor's measurement does not reproduce."*

I re-ran the same vendor read (`claude agents --json --all`) at **10:36** and
again at **10:49** on 2026-08-09, win32, `claude 2.1.226` — the same box and the
same vendor build the lane measured on, some hours after its snapshot (the lane
committed at 10:28):

```
=== DETECTOR CONTROL, RUN FIRST (wave 38) ===
  positive limb  done_with_keys(shaped) = 2 (expect 2)
  negative limb  done_with_keys(no-done roster) = 0 (expect 0)
  reverse-ce control  reverse_counterexamples(shaped) = 1 (expect 1: c4)
  opposites control  opposites(shaped) = ['c1', 'c2', 'c3', 'c4'] (expect c1,c2,c3,c4)
  opposites AGREE limb  opposites(NEG) = [] (expect [] -- a live entry agrees)
  CONTROLS PASS

=== REAL ROSTER ===
  entries: 139
  state histogram: {'done': 71, 'failed': 2, 'stopped': 26, 'blocked': 33, None: 2, 'working': 5}
  entries carrying pid or status: 9
  done entries: 71
  done entries STILL carrying pid/status: 1
```

The counter-example:

```json
{ "pid": 4436, "id": "b9b2124d", "cwd": "C:\\proga\\fleet-w50-live",
  "kind": "background", "startedAt": 1786251635724,
  "sessionId": "b9b2124d-2c4a-4dde-88b1-c16a992baf8b",
  "name": "fleet|w50-live|# w50 lane â€” three readers of \"is this t",
  "status": "idle", "state": "done" }
```

(The `â€”` is the vendor's own mojibake for an em dash in the task
title, reproduced verbatim rather than cleaned up.)

**That entry is the w50-live lane's own session** — the same sid the report's
test file hard-codes as `SID` at `tests/test_liveness_readers.py:28`. And the
process is real:

```
=== pid detector CONTROL, run first ===
  own pid 45012 -> True (expect True)
  bogus pid 999999 -> False (expect False)

=== 9 keyed entries vs the OS ===
  None     busy  pid=20704   alive=True  4983ab63
  None     idle  pid=37220   alive=True  88ba0258
  blocked  idle  pid=38336   alive=True  bfe71706
  working  busy  pid=33120   alive=True  a1928a95
  working  busy  pid=41176   alive=True  5bd99e65
  working  busy  pid=26660   alive=True  bd8542c8
  working  busy  pid=41464   alive=True  93f5c952
  done     idle  pid=4436    alive=True  b9b2124d
  working  busy  pid=38740   alive=True  2d3724ff
  ALIVE: 9/9
```

(The report's §3.2 measured 8/8 keyed entries alive on 137. Nine of nine here —
same shape, two more sessions on the box. **CLEARED**, and the one that matters
is row 8.)

**It is not a blip.** Two captures 25 minutes apart, identical:

```
roster.json   entries=139  done=71  done-with-keys=1  [('b9b2124d', 4436, 'idle')]
roster2.json  entries=139  done=71  done-with-keys=1  [('b9b2124d', 4436, 'idle')]
```

This is precisely the shape `_roster_live_sids`'s own docstring records from
macOS on 2026-07-19 — *"a finished bg session's host process can LINGER after
its turn ends -- the entry keeps `pid` AND `status` (\"idle\") with
`state:\"done\"`"* — **occurring on win32.** The parenthetical the report set out
to correct is false in the direction the predecessor said it was, and the report
declared the opposite.

**Why the lane's zero was honest and its inference was not (BELIEVED).** The
shape is a *turn-end transient that then persists*. A session reading the roster
is by construction `busy` at that instant, so its own entry cannot exhibit it —
and the entry that produced it was the lane's own. The lane ran a correct
detector control (wave 38's lesson) and then generalised a single snapshot into
*"does not reproduce"*. A control proves the detector can see the shape; it
proves nothing about whether the window was sampled. **That is a new lesson, not
one the repo has already paid for: wave 38 says run the control; this says the
control does not license the generalisation.**

**What follows it down.** Each of these is a load-bearing statement in the
report, and each is now false or unsupported:

| § | claim | status |
|---|---|---|
| §0, §3.1, §7-row-2 | "the predecessor's measurement does not reproduce" | **FALSIFIED** |
| §3.3 | "on a win32-shaped roster ... deleting the `state != \"done\"` clause changes **no answer**" | **FALSIFIED, MEASURED below** |
| §4.1 | "**zero instances** on this win32 roster" | the sharper `{done,busy,keys}` shape is still 0; its enabling condition is 1 and live |
| §3.5 | the proposed replacement docstring — *"this clause is currently inert here"*, *"It is load-bearing on posix"* | would ship a **false statement into `bin/fleet.py`** |
| §5.2 | "inert on win32 (where key presence tracks the process faithfully)" | key presence does **not** track the process faithfully here |
| §6.4 M5 | "This mutant **SURVIVES on win32 today** ... the test must use a synthetic posix-shaped entry" | wrong twice — see F1b |

**§3.3 falsified, MEASURED**, against the real roster with the real predicate:

```
=== §3.3: is the done-clause INERT on THIS win32 roster? ===
  with clause    : 8
  without clause : 9
  DIFFERENCE     : ['b9b2124d-2c4a-4dde-88b1-c16a992baf8b']
  INERT? False
```

The clause is not inert. It changes exactly one answer, and that answer is the
difference between `fleet respawn` refusing and proceeding on a body whose OS
process is alive — the file's own named unrecoverable invariant.

**F1b — and the good news, MEASURED.** The M5 mutant (delete
`and e.get("state") != "done"`) is **already killed by the shipped test file**:

```
M-E  claims: the state!=done clause is load-bearing
      -> rc=1  1 failed, 19 passed in 3.15s   ==> KILLED (test went RED)
      restored, sha256 match: True
```

So the branch's *tests* are right about the clause and the branch's *report* is
wrong about it. The build brief's instruction to reach for "a synthetic
posix-shaped entry" because the mutant "survives on win32" is unnecessary — and
worse, it teaches the successor that this divergence is unreachable on the
platform where it is, right now, reachable.

**What this does NOT break.** The field-conflation diagnosis stands: three facts
in three fields, `_roster_live_sids` answering a process question with a
run-fact. F1 makes that diagnosis *stronger*, not weaker — on this roster the
`state` field and the key-presence field genuinely disagree about the same
process. The ruling in §5.1 is untouched.

**Remedy (BELIEVED, one line):** re-measure, correct §0/§3.1/§3.3/§3.5/§4.1/§5.2
and §6.4 M5, and re-tag §7 row 2 from *"the premise under it did not reproduce"*
to *"the premise reproduces; the brief's causal inference from it is still
wrong"* — which is the finding the lane actually earned, and it survives intact.

---

## 1. MAJOR

### F2 — MAJOR — the §2.2 retraction is recorded but not completed; two later sections still stand on the retracted premise

**MEASURED, by reading.** §7.7.3 retracts, unprompted and creditably, the claim
that *"every one of these callers already refuses on an unfetchable roster or
spares on an unknown one"*, because `_wedged_release_gate` **fails OPEN**. The
brief asked me to check whether the correction is complete. **It is not.** Two
places still assert the retracted generalisation, and one of them is inside §2.2
itself, two lines above the corrected table:

* **§2.2, the asymmetry paragraph:** *"For the 9 non-display sites a false
  **dead** is unrecoverable and a false **alive** is a recoverable refusal."*
  Site 10's own false-alive cost, in the table directly below, is *"every
  mutating verb refused fleet-wide"* — which §6.3 calls an outage. Not a
  recoverable refusal.
* **§5.6:** *"Those 9 sites are correct **today** because their callers
  independently re-derived **the same conservative interpretation** of an
  out-of-band UNKNOWN. That is not a property anybody is enforcing; **it is nine
  coincidences.**"* Site 10 re-derived the **opposite** interpretation,
  deliberately, and says so in its own docstring (`bin/fleet.py:15459`).
* **§6.3 step 2, closing sentence:** *"the coincidence becomes a property, and
  nothing else changes"* — same framing, over all 9.

**Why it matters.** §5.6 is the *"is it worth fixing"* argument, and its
conclusion is "make the coincidence a property". A successor who reasons from
§5.6 and does not cross-read §6.3's table performs exactly the change §7.7.3 says
would arm the gate on every transient roster failure and refuse every mutating
verb fleet-wide. §6.3's mapping table and M2(b) are correct and would catch it —
so the report contains both the safe and the unsafe reading, and the unsafe one
is in the section that motivates the work.

This is the shape the repo has shipped before, and the brief predicted it
precisely: *a correction recorded in one section while a later section still
assumes the old claim.*

### F3 — MAJOR — 3 of the 20 tests assert source text or arithmetic, not behaviour; four mutants that break the properties they name survive the whole file

**MEASURED.** Mutation contract, enforced in the driver, not in prose: every
patch asserts `occurrences == 1` **before anything runs** and aborts on 0 or >1;
the floor is run first on a clean tree; restore is byte-identical and proved by
sha256; no run ever starts with a mutant on disk. All mutation was done on a
`git archive HEAD` scratch copy — `bin/fleet.py` in this worktree was never
written.

```
FLOOR sha256: b76dc65d6007ba71e6c59dd47f6ac0502f92588466a22dfd1d1b5a2e4b50ef2c
=== FLOOR (clean tree, mutant-free -- run BEFORE any patch) ===
  liveness file: rc=0  20 passed in 2.09s
```

Each mutant below was then run against the **full 20-test file**, not only
against the test it targets:

```
FLOOR (clean tree, 20-test file under gate): 20 passed in 10.46s
FLOOR failure set size: 0

M-B2 (respawn proceeds on unfetchable roster when --force)
    20 passed in 3.64s
    NEW failures vs floor: 0
    ==> SURVIVED the 20-test file under gate
    restored byte-identical: True

M-C (clean DOOMS instead of sparing on an unreadable roster)
    20 passed in 3.16s
    NEW failures vs floor: 0
    ==> SURVIVED the 20-test file under gate
    restored byte-identical: True

M-A (the _supervisor_gate staleness disarm deleted)
    20 passed in 3.46s
    NEW failures vs floor: 0
    ==> SURVIVED the 20-test file under gate
    restored byte-identical: True

M-D (a Q1 call site relocated out of _wedged_release_gate)
    20 passed in 2.72s
    NEW failures vs floor: 0
    ==> SURVIVED the 20-test file under gate
    restored byte-identical: True

FINAL: True
```

*Disclosure on the receipt above: my first driver labelled these
"SURVIVED the whole suite" while running only the file under gate. The label was
wrong, not the result; it is re-run and re-pasted verbatim here with the honest
label. What "whole suite" was **not** measured for these four is stated in §8.*

**M-A — `test_the_gate_disarms_on_the_same_staleness_the_watcher_read_as_death`.**
I deleted the disarm outright (`if age > SUPERVISOR_CLAIM_STALE_SECONDS:` →
`if False:`). The test stayed green. It does not call `_supervisor_gate`; it
constructs `stale_at = now - (STALE + 60)` and then asserts
`fresh_age <= STALE < stale_age`. That is an identity about `timedelta`, true for
any positive constant, and it would pass with the entire gate deleted. Its own
docstring concedes the shape — *"the disarm is a pure comparison and this is the
comparison"* — but re-implementing the comparison in the test is what makes the
production comparison untested. **The report's §4.3 presents this as MEASURED
evidence that the disarm exists; the test measures nothing about it.**

**M-B / M-B2 — `test_respawn_must_stay_conservative_toward_alive`.** The test is
`assert "refusing respawn " in src and "until the old session's liveness" in src`
— a substring search over `bin/fleet.py`'s own text. I planted two mutants. The
crude one replaced the refusal with `pass` and left the message behind as a
comment:

```
M-A  claims: the stale beat DISARMS _supervisor_gate
      -> rc=0  1 passed in 1.36s   ==> SURVIVED (test stayed GREEN)
      restored, sha256 match: True

M-B  claims: respawn REFUSES on an unfetchable roster
      -> rc=0  1 passed in 1.24s   ==> SURVIVED (test stayed GREEN)
      restored, sha256 match: True

M-C  claims: clean SPARES on an unreadable roster
      -> rc=0  1 passed in 1.25s   ==> SURVIVED (test stayed GREEN)
      restored, sha256 match: True

M-E  claims: the state!=done clause is load-bearing
      -> rc=1  1 failed, 19 passed in 3.15s   ==> KILLED (test went RED)
      restored, sha256 match: True
```

**Because the crude M-B is weaker than my prose about it**, I also planted the
realistic one, and *that* is the finding I am reporting:

```python
-    if not roster_ok:
+    if not roster_ok and not getattr(args, "force", False):  # MUTANT M-B2
         raise FleetCliError(
             f"{name}: could not fetch the native roster -- refusing respawn "
             "until the old session's liveness can be verified"
         )
```

The refusal is kept, byte-identical and reachable. A `--force` bypass is added in
front of it. `fleet respawn --force` will now proceed on an unfetchable roster —
the branch that produces two live sessions under one name, which §2.2 calls *"the
file's own named unrecoverable invariant"*. **20 passed.**

**M-C — `test_clean_must_stay_conservative_toward_alive_too`.** The test asserts a
**comment** is present: `assert 'None means "the roster is unknown", which
SPARES' in src`. Mutant:

```python
-    live_sids = _roster_live_sids(roster_entries) if roster_ok else None
+    live_sids = _roster_live_sids(roster_entries)  # MUTANT M-C
```

`cmd_clean` now dooms instead of sparing on an unreadable roster — §5.1's named
irreversible case, *"a false dead deletes a live worker's journal"*. The comment
survives, so the test survives. **20 passed.** This is wave 35's shape exactly,
in the file written to answer wave 35.

**Fair statement of scope.** These are characterising tests and the report never
claims they are the fleet's only guard. What the report *does* claim (§4) is that
all 20 "reproduce the disagreements" and that a green run is a receipt. For these
three, a green run is a receipt that a string is still in a file.

### F4 — MAJOR — the census pins a COUNT, not a population; the one thing its own failure message names is the one thing it cannot detect

**MEASURED.** `test_roster_live_sids_has_eleven_call_sites_not_ten` asserts
`len(calls) == 11` and fails with `f"call sites moved: {calls}"`. It never
asserts *which* lines or *which* scopes. Two-patch mutant, `occurrences == 1`
asserted on each:

```python
# part 1 -- site 10 no longer consults Q1 at all
-    live_now = _releaser_live_sids(claim, _roster_live_sids(payload),
+    live_now = _releaser_live_sids(claim, set(),  # MUTANT M-D pt1

# part 2 -- a compensating call, so the AST count is unchanged
+def _mutant_d_decoy(entries):
+    return _roster_live_sids(entries)  # MUTANT M-D pt2
```

`_wedged_release_gate` — the site the report itself calls **"the trap"** — has
been removed from the Q1 population, and the census reports 11 and passes. **20
passed.**

**Wave 35's four mutant shapes, actually planted** — the brief asked for these by
name, so they are four real patches, not four predictions:

```
FLOOR (clean tree): rc=0  1 passed in 2.24s

W35-1 ALIAS: rebind the name, call the alias at one site
    rc=1  1 failed in 2.23s
    >       assert len(calls) == 11, f"call sites moved: {calls}"
    ==> KILLED (census went RED)
    restored byte-identical: True

W35-2 WHITESPACE: `_roster_live_sids (entries)` at one site
    rc=0  1 passed in 2.67s
    ==> SURVIVED (census stayed GREEN)
    restored byte-identical: True

W35-3 EXTRA CALL inside an already-approved function
    rc=1  1 failed in 2.26s
    >       assert len(calls) == 11, f"call sites moved: {calls}"
    ==> KILLED (census went RED)
    restored byte-identical: True

W35-4 RELOCATE: drop site 10, add a decoy (count unchanged)
    rc=0  1 passed in 2.45s
    ==> SURVIVED (census stayed GREEN)
    restored byte-identical: True

FINAL: True
```

**Two of four killed, and I want to be exact about the two that were not.**
W35-2 (whitespace) survives **correctly** — the census is AST, not grep, so a
whitespace variant is not a defect it should detect; that shape defeated wave
35's *grep* census and this one is immune by construction. **W35-4 is the real
survivor**, and it is the same patch as M-D above.

So the honest scorecard is **not** "all four survived" as in wave 35, and it is
not "all four killed" either: **the census defeats the two shapes that change the
count and is blind to the one that preserves it.**

Contrast `test_the_heartbeat_census_has_no_hole`, in the same class, which
asserts `all(s.startswith("cmd_sup_") or s.startswith("_cmd_sup_"))` over the
scopes. **That test is the strongest thing in the file.** The `_roster_live_sids`
census needs the same treatment: pin the scope multiset, not the integer.

**CLEARED alongside it:** the census's *substance* reproduces exactly. My own
AST walk, own helpers, own controls — zero limb, non-zero limb, string-shape
limb — returns the same 11 sites at the same lines as §2.2's table, with no
attribute-call and no alias-shaped bare reference anywhere in the file:

```
=== CONTROLS (run first) ===
  zero limb   calls('zzz_no_such_fn_anywhere') = 0 (expect 0)
  nonzero limb calls('_fetch_agents_roster')   = 18 (expect >0)
  shape limb  string-constant mentions of _roster_live_sids = 2 (expect >=1)
  raw textual lines containing _roster_live_sids = 14

=== _roster_live_sids CALL SITES ===
   8230  _cmd_respawn_native
   8249  _cmd_respawn_native
   8255  _cmd_respawn_native
   9412  _cmd_respawn_supervisor
   9451  _cmd_respawn_supervisor._any_live
   9767  cmd_clean
   9974  _archive_eligible
  15180  _render_boot_bundle
  15230  cmd_sup_boot
  15460  _wedged_release_gate
  18559  _doctor_check_supervisor_wedge
  TOTAL name-calls = 11
  attribute-calls  = []
  bare non-call Name refs (alias shape) = []
```

14 textual lines = 11 calls + 1 def + 2 string mentions, exactly as §2.2 says.

**11, not 10, is right.** The brief was wrong and the lane corrected it correctly.

### F5 — MAJOR — the 13th reader: `_record_is_live` (`:2993`), the registry-side Q1 the census never opened

**MEASURED.** The brief asked me to find the 13th reader or prove the population
closed. It is not closed. `_record_is_live` is a shipped liveness predicate,
absent from §2.3's reader table and absent from the test file's
`test_every_reader_named_in_the_brief_still_exists` name list:

```python
def _record_is_live(rec) -> bool:
    """A record that could plausibly BE an acting body right now: not archived,
    not marked dead. [docstring elided -- 3 further lines]"""
    return (isinstance(rec, dict) and rec.get("archived_at") is None
            and rec.get("status") != "dead")
```

Three call sites: `_acting_worker_identity:3156`, `_releaser_body_is_tombstoned:14815`,
`_tombstone_releasing_body:16534`.

**It answers Q1 from the registry rather than the roster, and it disagrees with
the report's Q2 reader on the same record in the same process:**

```
   status=working         _record_is_live -> True
   status=idle            _record_is_live -> True
   status=dead            _record_is_live -> False
   status=dead-suspected  _record_is_live -> True
   status=stopped         _record_is_live -> True
   status=failed          _record_is_live -> True
   status=limited         _record_is_live -> True
   status=blocked         _record_is_live -> True

  CONTROL: archived record -> False (expect False)
  CONTROL: non-dict        -> False (expect False)

  KEY DISAGREEMENT: a record recompute_worker_native just demoted to
  dead-suspected (no roster entry, no fresh outcome) is:
    recompute_worker_native([]) -> dead-suspected
    _record_is_live(that record) -> True
```

`recompute_worker_native` demotes a record to `dead-suspected` precisely because
it could find no life for it; `_record_is_live` reads that record and calls it
live. **This is the same class as the lane's own 12th-reader finding, one field
deeper**, and it lands on the report's own `dead-suspected` argument (§5.3) —
the accumulating state that reached 234h across five husks is *live* to this
reader for its whole 234 hours.

**Why it bites the ruling specifically.** `_record_is_live` reaches
`_wedged_release_gate` — "the trap" — through the tombstone arm of
`_releaser_live_sids`, which §2.3 names (*"tombstone arm, then `released_by in
live_sids`"*) without opening. §6.2's predicate is
`roster_body_state(roster_ok, entries, sid)`: roster arguments only, no registry
argument, no place for this reader. **Build §6 as specified and a fourth spelling
of Q1 survives the consolidation, inside the one gate the report warns hardest
about.**

I say this without claiming the lane was careless: it found a reader its brief
missed, which is more than the brief asked for. But the population is
**demonstrably not closed**, and the report asserts closure by omission rather
than proving it.

### F6 — MAJOR — §6.3's call-site instruction is not implementable at 5 of the 9 sites, and §6.1/§6.2/§6.3 give three inconsistent site counts

**MEASURED, by reading all 11 call sites.** §6.3 step 2 says:

> *"The 9 non-display Q1 sites — replace `if not roster_ok: <...>` +
> `sid in _roster_live_sids(...)` with a single `roster_body_state(...)` switch."*

Only **4** of the 11 sites have a per-sid shape at all — `8230`, `8249`, `8255`,
`9412`, all inside respawn. The other **7 consume the SET**:

| site | actual shape | can it take a per-sid switch? |
|---|---|---|
| `9451` `_any_live` | `bool(gate_sids & _roster_live_sids(entries))` | no — set intersection over a sid union |
| `9767` `cmd_clean` | `_roster_live_sids(...) if roster_ok else None`, passed to `_clean_spares_released_body_evidence` | no — the callee's signature is the tri-state channel |
| `9974` `_archive_eligible` | set into `_releaser_live_sids` | no |
| `15230` `cmd_sup_boot` | set into `supervisor_claim_decision` | no |
| `15460` `_wedged_release_gate` | set into `_releaser_live_sids` | no |
| `15180` display | `len(live)` | no |
| `18559` doctor | set into `supervisor_claim_decision` | no |

So **5 of the 9 "non-display" sites cannot take the switch as written**, and for
those five UNKNOWN stays out-of-band — which is the precise defect the ruling
exists to remove. Site 10, the trap, is one of the five.

**`_archive_eligible` sharpens it.** Its signature is
`_archive_eligible(name, record, roster_entries, now, ttl_hours=)` — it takes no
`roster_ok` and receives `[]` on failure, so **the site itself cannot distinguish
UNKNOWN from GONE**; the refusal lives in the caller at `:10501`. Giving site 7
the tri-state requires a signature change §6.1's file table ("11 call sites
re-pointed; 1 docstring corrected") does not budget. The same is true of
`_clean_spares_released_body_evidence` and `supervisor_claim_decision`.

**And the counts do not agree with each other:**

| § | says |
|---|---|
| §6.1 | "**11 call sites** re-pointed" |
| §6.2 | "`_roster_live_sids` stays. It **keeps its 11 call sites** and becomes a thin wrapper" |
| §6.3 | "**The 9 non-display** Q1 sites — replace ..." |

11 re-pointed and 11 kept are mutually exclusive. §6.2 concedes the set problem
for `_releaser_live_sids` alone and never reconciles it with §6.3's nine.

**This does not refute the ruling.** *One canonical value, per-reader policy* is
implementable — but as a set-returning tri-state (`live`, `gone`, `unknown` as a
`(verdict, set)` or a mapping), not as the per-sid scalar §6.2 specifies. The
successor must design that, and §6 currently tells them they do not have to.

---

## 2. MINOR

### F7 — MINOR — the `INVERT-ON-BUILD` count is stated three different ways, and the report's own prescribed check returns a fourth

**MEASURED.**

| § | says |
|---|---|
| §4 | "**Five** carry `INVERT-ON-BUILD` (`grep -c` it)" |
| §6.1 | "Invert the **7** `INVERT-ON-BUILD` tests" |
| §6.4 M7 | "the **5** `INVERT-ON-BUILD` tests" |

```
$ grep -c "INVERT-ON-BUILD" tests/test_liveness_readers.py
6
```

Six: five test markers (`:219`, `:252`, `:327`, `:352`, `:455`) plus the module
docstring at `:6`. The true count of marked tests is **5**; §6.1's **7** has no
support anywhere; and the verification command the report tells the reader to run
returns none of the three numbers. A successor told to invert seven tests will
either invent two or stop looking for the five.

### F8 — MINOR — §6.5's re-pin numbers do not reproduce under any population I could construct

**MEASURED**, driving the shipped enforcer (`tests/test_self_citations.py`) with
the report's own controls at both ends of the range (insert@0 → all, insert@EOF →
0), which passed for every population:

```
=== CONTROLS AT BOTH ENDS, every population ===
  SELF_CITATIONS (occurrences)       n=42  insert@0=42  insert@EOF=0   @3714=34  @14656=8   @16779=2
  SELF_CITATIONS distinct targets    n=33  insert@0=33  insert@EOF=0   @3714=27  @14656=6   @16779=1
  distinct citing LINES (by target)  n=25  insert@0=25  insert@EOF=0   @3714=21  @14656=8   @16779=2
  FUNCTION_QUALIFIED                 n=5   insert@0=5   insert@EOF=0   @3714=5   @14656=0   @16779=0
  ALL CONTROLS PASS (insert@0 re-pins ALL, insert@EOF re-pins 0)

  len(CITED_SITES) = 13
  report §6.5 says: n=36  @3714=26  @14656=7  @16779=2
```

No population yields 36 / 26 / 7. **The ruling those numbers support is
unaffected and in fact strengthened**: the ranking is right, the ratio is ~4×,
`:14656` is the correct insertion point, and my 8 falls inside the report's own
"~7–9 re-pins" estimate. What does not survive is the presentation of 36/26/7 as
MEASURED constants a successor can budget against without re-running.

### F9 — MINOR — "60 of 137" is one population counted twice; the real figure is 131 of 139

**MEASURED.** The brief asked whether the two 60s are one population or a
coincidence. **They are one population, and reusing it understates the lane's own
finding by more than half.**

```
  reverse counter-examples (not-done AND keyless): 60
    by state: {'failed': 2, 'stopped': 26, 'blocked': 32}

  _roster_entry_has_life_signal vs _roster_live_sids -- DISAGREE on: 131 of 139
    by state: {'done': 71, 'failed': 2, 'stopped': 26, 'blocked': 32}
  AGREE on: 8
    by state: {None: 2, 'blocked': 1, 'working': 5}

  reverse-CE population == opposites population? False (rc=60 op=131)
```

The 71 keyless `done` entries disagree too — `_roster_entry_has_life_signal`
counts `"done"` as proof of life, `_roster_live_sids` excludes it by the done
clause. So §2.3's *"the exact **opposite** ... on 60 of 137"* and §7's *"on
one-third of the live roster"* should read **~94%**. The report's own test proves
this: `test_life_signal_and_roster_live_are_exact_opposites_here` iterates
`("done", "failed", "stopped", "blocked")` — **including `done`** — so the test
asserts the wider property the prose narrows.

*Disclosure: my first draft of the opposite-detector's control expected
`['c3','c4']` and **failed**, for exactly this reason. The control caught my
error before the data did; I fixed the control, not the detector.*

### F10 — MINOR — the `LIVE_SHAPE` fixture is not verbatim, and two places say it is

**MEASURED.** The test file header: *"every roster entry below is a literal
transcribed from a real `claude agents --json --all` snapshot"*. Report §4.1
labels the block `# verbatim from the live roster`. In fact
`TestDisagreementOne.LIVE_SHAPE` carries `sessionId: SID` — the **lane's own**
sid, `b9b2124d` — while `state`/`status`/`pid`/`name` come from a different
entry: `bfe71706-88b7-446e-a4c1-c31fe6fd6295`, `sup|inc-20260809T014912Z-c477|boot`,
pid 38336 (which I measured alive, so §0's prose about that entry is accurate).
The name is also abbreviated to `sup|inc-c477|boot`.

Harmless to the test — any sid works. But "verbatim" is the word that stops a
reader re-checking, and this fixture is a splice of two entries.

### F11 — MINOR — the floor-delta ordering claim cannot be verified by anything that outlives the session

**MEASURED (the absence).** §4 tags as MEASURED: *"zero floor delta (predicted in
the journal before running, then measured)"*. The journal is
`state/journals/w50-live.md` — gitignored, outside the repo, a single mutable
file with one mtime (10:28). Nothing preserves the ordering; the claim is
self-attested. That is a **BELIEVED**, not a MEASURED.

Not a defect in the branch — a limit on what the receipt proves, and the brief
asked me to check it specifically. If pre-registration is to mean anything here,
the prediction has to land somewhere append-only or committed.

---

## 3. THE SCOPE-NARROWING CALL — the brief ranked this first; I rank it third

The brief put the reclassification of disagreement 2 at the top because it is the
most expensive error class. **The ranking was reasonable; the evidence puts the
weight elsewhere (F1, F3, F5), and the brief asked me to say so if it did.** Here
is the grade it asked for.

**Is the G9 mechanism sufficient? YES, MEASURED — and I verified it in the code,
not only in the lane's test.** `wait_for_workers` (`:7163`) computes
`epoch_frozen = native_epoch_suspicious(...)` once per poll at `:7200` and then,
per worker, `if epoch_frozen: continue` at `:7212` — no recompute, no message.
`native_epoch_suspicious`
returns True on `not roster_ok`, and also on an empty roster while any record
still says `working`. The symptom follows directly.

**Is it necessary? NO — and the report says so in §1 and §4.2, honestly and
unprompted.** I checked the second mechanism it names and it holds up:
`bin/hooks/stop_outcome.py:239` — *"READ-ONLY registry lookup (invariant 6: hooks
never write fleet.json)"* — so fleet is a poll, not a push, and a cached status
read shows `working` for a finished lane with no freeze involved. **CLEARED: that
measurement is correct.** I also searched `state/journals/` and
`knowledge/lessons.md` for an incident record and found none, confirming §1's
statement that the incident cannot be attributed.

**So: is the honesty matched by the conclusion? NO. MEASURED, by where the caveat
appears and where it does not.**

| section | what a reader gets |
|---|---|
| §1 body, §4.2 | *"I did **not** confirm this is the incident's mechanism. ... Both are real; I have receipts for the first and only code-reading for the second."* |
| §0 HEADLINE | *"Disagreement 2 is **NOT** [one class] — it is a **deliberate, correct safety freeze** with no surface."* — flat, no caveat |
| §7 row 1 | *"**#2 is not** — it is a correct, deliberate safety freeze whose only defect is silence. **Unifying it would produce a wrong fix.**"* — flat, no caveat |
| §5.5 | *"**Not** removing the epoch freeze"* — flat |

The two sections a hurried successor reads — the headline and the
where-the-brief-was-wrong table — state an **attributed** cause. The
non-attribution lives only in §1's body and §4.2.

**The concrete risk, stated plainly (BELIEVED).** The report's remedy for
disagreement 2 is *a surfaced freeze*. If the incident was mechanism 2, the
surface never fires for it: no freeze happened. The successor ships a surface,
the wave reads as having fixed disagreement 2, and the original symptom is
untouched. That is the exact failure the brief describes, and it is live here.

**But I will not call the reclassification wrong, because it probably is not.**
The G9 freeze is genuinely a different thing from a reader keying on the nearest
field, and unifying it with Q1's tri-state genuinely would produce a wrong fix —
the freeze must survive any canonical value. **What is wrong is the confidence,
not the classification.** MINOR-severity as a defect; I flag it here rather than
in §2 only because the brief asked for it by name.

**Remedy:** carry §1's caveat into §0 and §7 verbatim, and add to §6 a step that
*attributes the incident* — the cheapest version is a one-line log when
`epoch_frozen` short-circuits a wait, which turns the next occurrence into
evidence instead of a second unattributable report.

**One supporting observation, MEASURED, that the report does not make and that
argues its own case.** `wait_for_workers` passes **all** `workers` to
`native_epoch_suspicious`, not just `live_pending`. So one unrelated record
anywhere in the registry with `status == "working"` and a sid freezes the wait for
**every** worker when the roster returns `[]`. The report's §4.2 fixture has a
single worker, so it never measured the amplification. This strengthens "the
freeze needs a surface"; it does not weaken it.

---

## 4. THE TRI-STATE — does it survive?

**YES on the ruling, NO on §6.2's signature.** F6 has the implementability
measurement. Two further checks the brief asked for:

**The clearing question — CLEARED, and this is the report at its best.** The brief
warned that a third value with no clearing ritual reproduces `dead-suspected`
(five husks, 234h, *a signal nobody is obliged to act on stops being a signal*).
§5.3 answers it directly and correctly: `dead-suspected` is **persisted** and
accumulates; Q1's UNKNOWN is **computed per call and never written**, so it cannot
accumulate because it has no storage, and its clearing ritual is the next roster
fetch. §6.4 M4 makes the no-persistence guarantee a mutant rather than an
assertion, and explicitly rejects a grep-based check in favour of asserting
`state/fleet.json` bytes after a full cycle. **That is a real answer, not a
dodge**, and the "who clears it" question is answered by *nobody has to*.

One caveat worth recording, BELIEVED, not a defect: §6.3 step 1 routes
`ROSTER_UNKNOWN` in `recompute_worker_native` down the `has_fresh_outcome` path,
which on a miss reaches `_investigate_no_outcome` and persists **`dead-suspected`**.
So the new value does not accumulate, but the pipeline still deposits into the old
unbounded one. The report is not proposing to fix `dead-suspected` and says so; a
successor should just not read §5.3 as having solved it.

**`_wedged_release_gate`'s fail-open — CLEARED as a design call, GATED as a
document.** The gate is right: a speed-bump at the top of every mutating verb must
not brick the CLI on a transient roster failure, its docstring says so
(`:15459`), and §6.3's mapping table and M2(b) protect it. What fails is F2 — the
report contains sentences elsewhere that would undo it.

---

## 5. GRADED THE OTHER DIRECTION — what held up

The brief asked me to say explicitly which parts survive attack. These do.

| claim | verdict |
|---|---|
| **11 call sites, not 10** | **CLEARED, MEASURED.** Reproduced exactly — same 11 lines, same scopes — by an independent AST walk with my own zero / non-zero / string-shape controls. Grep's 14 = 11 calls + 1 def + 2 string mentions. The brief guessed the grep over-counted; it under-counted, and the lane said so. |
| **The census's controls are real, not decorative** | **CLEARED.** The zero limb, the non-zero limb and the string-shape limb all discriminate against data that actually carries the hazard. |
| **The heartbeat census: 8 writers, all `sup-*` scopes, no hook writes it** | **CLEARED, MEASURED — re-derived independently**, own AST walk, own controls (`zzz_no_such_key` → 0; `status` → 34): `:15325 :15341 :15374 cmd_sup_boot`, `:16415 cmd_sup_checkpoint`, `:16429 cmd_sup_heartbeat`, `:18012 cmd_sup_handoff_complete`, `:18145 _cmd_sup_handoff_retire_all`, `:18239 cmd_sup_handoff_abort` — **8, all `sup-*`**; `grep -rn heartbeat bin/hooks/` → 0 hits. And `test_the_heartbeat_census_has_no_hole` asserts **scopes**, reconciles every textual occurrence against a classified AST node / comment / string interior, and puts a control on the control (`len(unclassified) >= 5`). **This is the strongest test in the file and the model the `_roster_live_sids` census should follow.** The `ast.Dict`-vs-`ast.Subscript` hole the lane found in its own apparatus and disclosed is a genuine catch. |
| **The `state != "done"` clause is genuinely pinned** | **CLEARED, MEASURED.** M-E killed: `1 failed, 19 passed`. |
| **Fleet is poll-not-push; `stop_outcome.py` never writes the registry** | **CLEARED.** `bin/hooks/stop_outcome.py:239`, invariant 6. §1's second mechanism is real. |
| **The field-conflation diagnosis** | **CLEARED, and F1 strengthens it.** Three facts in three fields; `_roster_live_sids` answers a process question with a run-fact. The brief told me to distrust a replacement diagnosis from the session that got the first one wrong. I attacked it and it held — and the live `done`+`pid:4436`+`status:"idle"` entry is a *second* instance of the same conflation, this time with `state` and key-presence disagreeing about one process. |
| **"4243 passed on BOTH floors"** | **CLEARED, MEASURED, both interpreters.** Re-run read-only in this worktree: `py -3.13` → `4243 passed, 14 skipped, 1 xfailed in 468.62s`; `py -3.10` → `4243 passed, 14 skipped, 1 xfailed in 418.00s`. Exact match on the pass count *and* the skip/xfail shape, on both. |
| **The read-only fence on `bin/fleet.py`** | **CLEARED.** `git diff w50/live w50/glive` empty; sha256 identical at floor, after every mutant, and now. |
| **No live fleet verb run by the lane** | **CLEARED, BELIEVED.** §8's claim is consistent with everything I can see: every reproduction in the test file is a pure-function or AST measurement, and the one vendor read is `claude agents --json --all`, which takes no `fleet.lock` and reads no fleet home. I cannot audit a session I did not run; nothing contradicts it. |
| **Self-disclosure of three own-work defects, unprompted** | **CLEARED and worth saying.** §7's seventh row discloses a reasoning error that had not shipped and that nobody would have found. F2 is that the disclosure is incomplete — not that it was not made. |

---

## 6. WHERE THIS BRIEF WAS WRONG

The dispatching brief asked me to assume it contains an error.

1. **"A 1214-line report."** It is **672 lines** (`wc -l docs/lanes/w50-live.md`).
   Immaterial to the gate, but the brief's own framing — *"a 1214-line report that
   a successor executes is a specification"* — is a number nobody re-derived.
2. **The ranking.** The brief put the scope-narrowing call first. **It is not
   where the weight is.** The scope-narrowing is a confidence defect with a real
   but bounded cost (§3 above). The expensive findings are F1 (a false headline
   that five sections and a build mutant descend from), F3 (three tests that
   assert text) and F5 (an unclosed reader population). The brief said to follow
   the evidence and say so; I am saying so.
3. **"`bin/fleet.py` being byte-identical means the branch is low-risk" — the
   brief flagged this as a likely error of its own, and it was right.** Every one
   of F1–F6 is in a document or a test, and the code is untouched.
4. **"Find the 13th."** The brief's numbering treats the census's 11 *call sites*
   and §2.3's *readers* as one sequence. There is no 12th reader in that sense —
   `_roster_entry_has_life_signal` is the fourth or eighth reader depending on how
   you count. I found `_record_is_live` and report it as F5 without adopting the
   numbering.

---

## 7. WHAT THE SUCCESSOR MUST DO BEFORE BUILDING §6

Ordered by cost of skipping.

1. **Re-measure the roster and correct F1's six sections.** One command, and it
   changes `bin/fleet.py`'s proposed docstring from false to true.
2. **Delete or rewrite §5.6's "nine coincidences" sentence and §2.2's asymmetry
   paragraph** so the `_wedged_release_gate` carve-out is stated everywhere the
   generalisation is (F2).
3. **Rewrite the three text-asserting tests as behavioural ones** and re-run M-A /
   M-B2 / M-C until they go RED (F3). The mutants are in this gate's ledger.
4. **Pin the census's scope multiset, not its integer** — copy
   `test_the_heartbeat_census_has_no_hole`'s shape (F4).
5. **Add `_record_is_live` to the census and decide whether it is Q1** (F5). If it
   is, §6.2's signature is wrong; if it is not, name what it is.
6. **Redesign §6.2's predicate to return a set-plus-verdict, not a per-sid
   scalar**, and budget the three callee signature changes §6.1 omits (F6).
7. **Reconcile 5 / 6 / 7 for `INVERT-ON-BUILD`, and re-derive §6.5's re-pin
   numbers** before quoting them as a budget (F7, F8).

---

## 8. WHAT I DID NOT DO

Stated so nobody reads a gap as a clearance.

* **I did not audit the lane's session for live-verb use.** §8's "NONE" is
  BELIEVED-consistent, not MEASURED (§5).
* **I did not test on posix.** §5.2's "load-bearing on posix" remains
  unmeasured by anyone — the report flags it as the one thing the build must
  measure there, and F1 now means the win32 side needs re-measuring too.
* **I did not run the whole repo suite against M-A/M-B2/M-C/M-D.** They survive
  the 20 tests under gate, which is the deliverable; whether some other test file
  catches them is unmeasured, and a successor should check before assuming they
  are unguarded fleet-wide.
* **I did not attempt to attribute the disagreement-2 incident.** I searched for
  a record and found none (§3); I ran no live verb to hunt one.

---

## 9. SAFETY — exactly what this gate ran

**Live fleet verbs run: NONE.** Not `status`, not `peek`, not `result`, not
`doctor` — the brief permitted those four and none was needed.

* **One live read:** `claude agents --json --all`, twice, captured to files under
  `$CLAUDE_JOB_DIR/tmp` outside the repo. Vendor CLI read-only listing; takes no
  `fleet.lock`, reads no fleet home, and is the same command `_fetch_agents_roster`
  shells out to.
* **No `fleet init`, no `FLEET_HOME` set or exported, no `--fleet-home` passed**
  — no fleet verb ran at all, so no scratch home was ever created and the
  normalised-`fleet home` gate had nothing to gate.
* `~/.claude/settings.json` and `~/.claude/fleet-homes.list` never opened for
  write; `~/.claude/fleet-homes.list` never appended to.
* **All mutation ran on a `git archive HEAD` scratch copy** at
  `$CLAUDE_JOB_DIR/tmp/mut`. `bin/fleet.py` in this worktree was never written.
  Every mutant asserted `occurrences == 1` before running anything, and every
  restore was proved by sha256 against the floor digest
  `b76dc65d6007ba71e6c59dd47f6ac0502f92588466a22dfd1d1b5a2e4b50ef2c`. No run
  started with a mutant on disk.
* One pid-liveness probe via `tasklist /FO CSV /NH`, parsed by row rather than by
  exit code — `tasklist /FI` prints `INFO: No tasks...` to **stdout** and exits
  **0** for a dead pid, so the obvious checks report every pid alive. Control run
  first, both limbs (own pid `True`, 999999 `False`).
* **Floors measured in this worktree, read-only, both interpreters:**
  `py -3.13 -m pytest -q` → `4243 passed, 14 skipped, 1 xfailed in 468.62s`;
  `py -3.10 -m pytest -q` → `4243 passed, 14 skipped, 1 xfailed in 418.00s`.
  **Exactly the report §4 / journal numbers, CLEARED.** The scratch mutation copy
  is a `git archive` export and therefore not a git repo, so 28 receipts /
  executable-bit tests fail there for that reason alone; every mutant verdict
  above is a differential against that copy's own floor, never against an
  assumed green.
* Branch `w50/glive` only. No push, no merge, no other ref moved.
  `bin/fleet.py` byte-identical.
