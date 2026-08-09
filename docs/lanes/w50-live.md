# `w50-live` — three readers of "is this thing alive", and they disagree

| | |
|---|---|
| Branch | `w50/live` |
| Base | `4d78f6c` (`docs(w49): journal the wave-49 landings, gates and stand-down`) |
| Lane | Research. **`bin/fleet.py` NOT modified.** This file + `tests/test_liveness_readers.py` are the whole diff. |
| Vendor | `claude --version` → `2.1.226 (Claude Code)` |
| Interpreters | `py -3.13` → 3.13.12; `py -3.10` → 3.10.1 |
| Live fleet verbs run | **NONE.** See §8. |
| `~/.claude/settings.json`, `~/.claude/fleet-homes.list` | never opened for write; no `fleet init`, no `FLEET_HOME` export |

Every line is tagged **MEASURED** (I ran it in this lane and read the output) or **BELIEVED**
(reasoning, or documentation I did not execute). Section §7 is the "where this brief was wrong"
section, and it is not a formality — **the brief's central measurement did not reproduce.**

---

## 0. HEADLINE

**MEASURED — the brief's load-bearing claim is false, and the true cause is cleaner than the one
it names.** The predecessor's finding that "a `done` roster entry keeps `pid`/`status` on Windows"
does **not** reproduce: 137 live entries, 69 of them `done`, **zero** carrying `pid` or `status`.

**MEASURED — the parenthetical is still false, in the opposite direction.** *"The two conditions
agree"* is a biconditional. The forward direction holds; the reverse has **60 counter-examples**
on the same snapshot (`blocked` ×32, `stopped` ×26, `failed` ×2 — all not-`done`, all keyless).

**MEASURED — the real cause of disagreement 1 is a field conflation, and it is live in the roster
right now.** The roster carries **three different facts in three different fields**, and
`_roster_live_sids` answers a question about one of them using another:

| roster field | the fact it states | evidence |
|---|---|---|
| `pid` / `status` **key presence** | **a host process exists** | **MEASURED: 8/8 keyed entries back a live OS process** (`tasklist` per pid, control limbs both passing — own pid `True`, bogus pid `False`). The converse (keyless ⇒ gone) is **BELIEVED**, not measured: a keyless entry carries no pid to check. |
| `status` **value** (`busy`/`idle`/`waiting`) | **the current turn's state** | MEASURED: 6 `busy` = mid-turn (4 w50 lanes + the current supervisor + 1 other session); 2 `idle` = process alive **between** turns |
| `state` (`working`/`done`/`stopped`/`failed`/`blocked`) | **how the last RUN ended** | MEASURED: outlives both — 129 of 137 entries carry a `state` and no process keys at all |

`_roster_live_sids` asks a *process* question (`is a body running?`) and answers it with key
presence **plus a `state` clause** — a run-fact. `recompute_worker_native` asks a *turn* question
and answers it with key presence **plus the `status` value**. On the same entry
(`state:"blocked"`, `status:"idle"`, `pid:38336` — a real supervisor, in the roster as I write
this, and **MEASURED to be a live OS process**) reader A says **LIVE** and reader B says **IDLE**.
That is disagreement 1, and it contains no `done` entry at all.

That entry is worth pausing on, because it is the whole finding in one row: the process **is**
alive (so reader A is right), its turn **is** over (so reader B is right), and its last run ended
`blocked` (so the field reader A consults is talking about neither).

**THE RULING (§5): one canonical *verdict* cannot serve every reader; one canonical tri-state
*value* can, and should.** The split is **CORRECT rather than merely current** — three genuinely
different questions with three genuinely different cost asymmetries — **but the split fleet has
today is not that split.** There are **four-and-a-half** implementations spread across those three
questions with no stated mapping. The defect is not that there are three readers; it is that
**only one question has a named predicate**, so the other two are answered by whichever field is
nearest, and the one ambiguity value every reader needs (`UNKNOWN`) is passed out-of-band and
re-interpreted eleven times.

**Verdict on the brief's framing question:** disagreements 1 and 3 are the same class (a reader
answering its question with the nearest available field). **Disagreement 2 is NOT** — it is a
deliberate, correct safety freeze with no surface. Unifying it with the other two would be a
mistake. §1 argues this.

**Is it worth fixing? YES, and it is cheap, but not where you would put it.** MEASURED: inserting
next to `recompute_worker_native` (`:3714`) re-pins **26 of 36** enforced self-citations;
inserting next to `_roster_live_sids` (`:14656`) re-pins **7**. §6 uses that number.

---

## 1. ARE THESE THREE INSTANCES OF ONE CLASS? — the brief's error #1, answered first

The brief asked me to say so in the first section if the unification framing is misleading. **It
is partly misleading, and here is the line.**

**Disagreements 1 and 3 ARE one class.** BELIEVED, on measured components. In both, a caller had a
question, no predicate in the tree was named for that question, and the caller keyed on the
nearest available field:

* #1 — `fleet respawn` wants *"is a body running?"*. `_roster_live_sids` is the nearest thing and
  it half-answers that, so respawn uses it. `fleet status` wants *"is this worker mid-turn?"*,
  finds nothing named for it either, and re-derives its own inline predicate 11,000 lines away.
* #3 — the watcher wanted *"is the supervisor body alive?"*. The supervisor surface is **file-only
  by mandate** and structurally cannot answer that (MEASURED: `cmd_sup_status`'s own docstring —
  *"READ-ONLY VIEW … no lock, no probe, no write"*; `_supervisor_tier_snapshot` — *"no roster
  read, no probe, no subprocess"*). The nearest field was `heartbeat_at`, so the watcher used it.

**Disagreement 2 is a DIFFERENT class, and calling it the same one would produce a wrong fix.**
MEASURED: the mechanism I can reproduce is `native_epoch_suspicious` — the G9 epoch freeze. When
the roster fetch fails, *or comes back empty while any native record still says `working`*, every
native verdict is frozen: `wait_for_workers` `continue`s past the worker **without recomputing**,
so a lane whose own recompute says `idle` stays `pending` until the wait times out
(`tests/test_liveness_readers.py::TestDisagreementTwo`, both limbs, with a control run first).

That is not a reader disagreeing with another reader. It is **one reader deliberately declining to
answer**, for a reason its docstring states and I endorse: *"a fresh daemon boot … must never be
read as 'everything died'."* The freeze is correct. **Its defect is that it is silent** — nothing
in `wait_for_workers`, `cmd_wait`, or `cmd_status` tells the caller that a freeze happened, so a
supervisor waiting on a finished lane sees "still working" and cannot distinguish it from a lane
that is genuinely still working. A canonical liveness *value* does not fix that. A *surfaced
freeze* does.

**Caveat, stated plainly (BELIEVED, not MEASURED):** I reproduced a mechanism that produces
disagreement 2's exact symptom. I could **not** tie it to the actual incident — there is no
incident record in `state/journals/` and I ran no live verbs to hunt one. A second mechanism
produces the same symptom and I cannot rule it out: **fleet is a POLL, not a PUSH.** MEASURED —
`bin/hooks/stop_outcome.py` writes *only* the outcome record and never touches the registry, so a
worker's `status` field stays at its last-committed value until some verb recomputes it. If the
supervisor read a cached `fleet status` table rather than re-running one, it would see `working`
for a finished lane with no freeze involved at all. **Both are real; I have receipts for the
first and only code-reading for the second.**

---

## 2. THE CENSUS (deliverable A)

Derived by AST, not grep, with a count control on every number.

### 2.1 The control, run first

```
control 'supervisor_epoch_check':       n=1  (expect non-zero)
control '_roster_live_sids':            n=11 (expect non-zero)
control 'zzz_no_such_function_anywhere': n=0 (expect ZERO)
control shape: '_roster_live_sids' appears inside n=2 string constants;
               the AST call census must NOT count them
```

MEASURED. The zero-limb proves the counter can report zero; the non-zero limb proves it can report
non-zero; the **shape** limb proves the specific hazard (a docstring mention) is *present in the
data*, so the control discriminates rather than passing vacuously (wave 42's lesson). All three
are re-derived on every run by `TestTheCensus::test_roster_live_sids_has_eleven_call_sites_not_ten`.

### 2.2 `_roster_live_sids` — **11 call sites, not 10**

MEASURED. Grep sees 14 lines; the AST sees 11 calls, and the difference is exactly 1 definition
+ 2 docstring mentions (`:8127`, `:18511`) — which is the brief's own suspicion (error #4),
confirmed with the number corrected upward rather than down.

| # | site | verb | question in the caller's terms | false ALIVE costs | false DEAD costs |
|---|---|---|---|---|---|
| 1–3 | `_cmd_respawn_native` `:8230,:8249,:8255` | `respawn` | "is the old body still running?" | a refusal the operator retries or `--force`s | **two live sessions under one name** — the file's own named unrecoverable invariant (`:8259`) |
| 4–5 | `_cmd_respawn_supervisor` `:9412,:9451` | `respawn supervisor` | same, over the whole sid union | same | same, plus a dual-supervisor claim |
| 6 | `cmd_clean` `:9767` | `clean` | "may I delete this body's state?" | a spared husk (`clean` again later) | **irreversible deletion of a live worker's logs/journal/mailbox** |
| 7 | `_archive_eligible` `:9974` | `archive`/`autoclean` | "is this record wedging a released claim?" | a record not archived | archiving the record the §7 gate reads → wedge becomes unclearable |
| 8 | `_render_boot_bundle` `:15180` | `sup-boot` | "how many bodies are up?" (display) | a wrong count in a bundle | a wrong count in a bundle |
| 9 | `cmd_sup_boot` `:15230` | `sup-boot` | "is the recorded claim holder alive?" | boot refused/frozen (recoverable) | **a second supervisor seizes a live claim** |
| 10 | `_wedged_release_gate` `:15460` | every mutating verb | "did the releasing body actually exit?" | every mutating verb refused fleet-wide | `fleet clean --yes` reachable from a third body |
| 11 | `_doctor_check_supervisor_wedge` `:18559` | `doctor` | "is the claim wedged?" (report) | a false FAIL row | a false PASS row |

**MEASURED asymmetry — and it is NOT uniform, which is the more useful finding.** For the 9
non-display sites a false *dead* is unrecoverable and a false *alive* is a recoverable refusal. But
the callers' policies on an *unknown* roster are not the same policy, and I checked all 11 rather
than generalising from the first two:

| policy on an unreadable/empty roster | sites | how |
|---|---|---|
| **refuse the verb** | 1–5, 7, 9 | `:8225`/`:9408` refuse outright; `:10501` refuses the whole archive on `epoch_frozen`; `:15228` freezes via `supervisor_epoch_check` |
| **spare the record** | 6 | `:9766` — *"None means 'the roster is unknown', which SPARES"* |
| **fail OPEN — permit the verb** | 10 | `:15459` — *"roster unreadable: fail OPEN"*. **Deliberately the opposite direction**: this gate runs at the top of *every* mutating verb, and a speed-bump that bricks the whole CLI on a transient roster failure is a worse outcome than a window in which it does not fire. |
| display / report only | 8, 11 | a wrong count in a bundle; a `True` row with a caveat (`:18551`) |

**That table is the ruling in miniature.** Three different UNKNOWN policies across sites reading
one fact — and each is right for its own site. `_roster_live_sids` is already the conservative
process-existence predicate and **it is the one reader in this census behaving correctly**; what is
missing is that UNKNOWN never reaches it as a value, so the policy lives in eleven places instead
of one.

### 2.3 The other readers — and the two the brief did not name

| reader | predicate (quoted) | question | asymmetry |
|---|---|---|---|
| `recompute_worker_native` `:3760` | `live = entry is not None and ("status" in entry or "pid" in entry)` then branches on `entry.get("status")` | **is this worker mid-TURN?** | liberal both ways; `dead-suspected` is advisory, never auto-respawned (MEASURED: not in `_NATIVE_STICKY`) |
| `native_epoch_suspicious` `:3783` | `not roster_ok` **or** (`entries` empty **and** any native record says `working`) | **can I trust ANY verdict this poll?** | false-suspicious costs wall-clock; false-trusting mass-demotes a live fleet to `dead-suspected` |
| `_roster_entry_has_life_signal` `:12964` | `"status" in entry or "pid" in entry` **or** `entry.get("state") in ("done","failed","stopped","blocked")` | **did this session ever ATTACH?** (handoff identity proof) | false-signal binds a husk to a handoff; false-none rejects a valid name-join |
| `_dispatch_grace_active` `:3649` | `not _launch_claim_expired(last_dispatch_at or created)` | **is the launch machinery still standing this up?** | deliberately conservative toward `working` |
| `heartbeat_at` age (`_supervisor_gate` `:15621`) | `(now - heartbeat_at) > SUPERVISOR_CLAIM_STALE_SECONDS` | **did the supervisor recently ACT as supervisor?** | false-fresh keeps a gate armed (safe); **false-stale silently DISARMS it** |
| `supervisor_epoch_check` `:14681` | `not roster_ok` or `not payload` | same as `native_epoch_suspicious`, for the claim path | freeze + page operator |
| `_releaser_live_sids` `:14818` (5 call sites) | tombstone arm, then `released_by in live_sids`, then the fork-steer sid union | **did the releasing body exit?** | built ON `_roster_live_sids`; inherits its answer |

**`_roster_entry_has_life_signal` is the reader the brief did not name, and it is the sharpest
one.** MEASURED: on all 60 keyless not-`done` entries it returns **`True`** while
`_roster_live_sids` returns **`set()`** — the two shipped predicates are *exact opposites* on
one-third of the live roster. Pinned by `TestTheReaderTheBriefDidNotName`. Both are right: one
asks *"did this ever attach"*, the other *"is it running now"*. Nothing in the tree says so.

### 2.4 `heartbeat_at` — the brief's error #3, MEASURED TRUE

**8 write sites, 6 read sites.** Every writer is inside `cmd_sup_boot`, `cmd_sup_checkpoint`,
`cmd_sup_heartbeat`, `cmd_sup_handoff_complete`, `_cmd_sup_handoff_retire_all`, or
`cmd_sup_handoff_abort` — all bound to `sup-*` CLI verbs at `:21406–:21427`. No hook writes it
(`grep -rn heartbeat bin/hooks/` → 0 hits). **The interface tier's diagnosis of its own incident
was correct.**

> **My own census had a hole, and the control is what found it.** The first version counted
> `ast.Subscript` stores only and reported **5** writers. A dict *literal* — `{"heartbeat_at":
> now_iso()}` — is an `ast.Dict`, not a `Subscript`. Three writers were invisible. The reconciling
> control (every textual occurrence must classify as a node, a comment, or a string interior)
> is what surfaced it, and it is now `TestTheCensus::test_the_heartbeat_census_has_no_hole`.
> A census with a hole reports a *smaller* number confidently, which is wave 35's mutant survival
> in miniature.

---

## 3. THE WINDOWS PARENTHETICAL — the brief's error #2

```
    (On Windows the two conditions agree -- done entries lose pid/status.)
```

**MEASURED, live roster, win32, 2026-08-09, 137 entries.** Detector control run **first** against
a shaped synthetic roster with a known answer of 2 (`PASS`), plus a negative limb on a `done`-free
roster (`PASS`). Only then against real data.

```
REAL roster: 137 entries, platform=win32
  state histogram: {'done': 69, 'failed': 2, 'stopped': 26, 'blocked': 33,
                    None: 2, 'working': 5}
  entries carrying pid or status: 8
  done-entries STILL carrying pid/status: 0
```

**§3.1 — The predecessor's measurement does not reproduce.** MEASURED: zero counter-examples in 69
`done` entries. The forward direction — *`done` ⇒ no keys* — **holds on this snapshot.** If the
predecessor measured otherwise, either the vendor changed between then and 2.1.226, or the
measurement was of a `blocked`/`stopped` entry read as `done`. I cannot distinguish those.

**§3.2 — The sentence is still false, because it claims a biconditional.** MEASURED: **60**
counter-examples to the reverse direction — entries that are not `done` and yet carry neither
`pid` nor `status`:

| `state` | keys? | `status` | n |
|---|---|---|---|
| `blocked` | keyless | — | **32** |
| `stopped` | keyless | — | **26** |
| `failed` | keyless | — | **2** |
| `done` | keyless | — | 69 |
| `blocked` | **keys** | `idle` | **1** |
| `working` | **keys** | `busy` | 5 |
| `None` | **keys** | `busy`/`idle` | 2 |
| | | | **137 ✓** (buckets reconcile to the roster length — a table that drops a bucket reads as "no such case") |

**The 8 keyed entries were then checked against the OS**, because "key presence is the process
fact" is a claim about processes and not about JSON. MEASURED: **8/8 back a live OS process.**
Control run first, both limbs: this interpreter's own pid → `True`, pid 999999 → `False`. The
checker parses `tasklist /FO CSV` rows rather than testing exit code or output-emptiness —
`tasklist /FI` prints `INFO: No tasks...` to **stdout** and exits **0** for a dead pid, so both of
the obvious checks would have reported every pid alive and confirmed the claim vacuously. That is
wave 38's shape, in a different tool.

**§3.3 — And the practical consequence the parenthetical implies — "the `done` clause is redundant
here" — is TRUE today, which is exactly why nobody noticed.** MEASURED
(`test_the_done_clause_is_inert_on_a_windows_shaped_roster`): on a win32-shaped roster the
key-presence test is *strictly stronger*, so deleting the `state != "done"` clause from
`_roster_live_sids` changes **no answer**. A clause that is inert on the platform you develop on
is a clause you cannot test by running the fleet.

**§3.4 — It is not the cause of disagreements 1 or 2.** MEASURED
(`test_the_split_survives_removing_the_done_clause_entirely`): the entry that splits the two
readers has `state:"blocked"`, not `done`. The brief's inference (its own error #2) is falsified.

**§3.5 — What the parenthetical SHOULD say (BELIEVED — proposed wording, not shipped):**

> *(On win32 the key-presence test is strictly stronger than the terminal-state rule, so this
> clause is currently inert here — measured 2026-08-09, 137 entries, 69 `done`, 0 with keys. It is
> load-bearing on posix, where the host process lingers and key presence is the condition that
> stops moving. Do not delete it because a Windows roster says it changes nothing. Note the
> converse does NOT hold on either platform: `stopped`/`failed`/`blocked` entries are keyless too,
> so "not `done`" is not "live" — see `_roster_entry_has_life_signal`, which answers the opposite
> way on exactly those.)*

---

## 4. THE THREE DISAGREEMENTS, REPRODUCED (deliverable B)

`tests/test_liveness_readers.py` — **20 tests, green on `py -3.13` and `py -3.10`, zero floor
delta** (predicted in the journal before running, then measured). Every roster literal in it is
transcribed from the real 137-entry snapshot, so the *shapes* are measured even though the
fixtures are synthetic.

**They PASS today.** Each asserts a contradiction that is currently true of shipped code, so a
green run is the receipt that the disagreement exists — not that it is fixed. **Five** carry
`INVERT-ON-BUILD` (`grep -c` it): a successor who unifies the readers and leaves this file green
has not landed the change.

### 4.1 Disagreement 1 — REPRODUCED ✅

```python
LIVE_SHAPE = {"sessionId": SID, "state": "blocked", "status": "idle", "pid": 38336,
              "kind": "bg", "name": "sup|inc-c477|boot", ...}   # verbatim from the live roster

assert SID in fleet._roster_live_sids([LIVE_SHAPE])                       # respawn: LIVE
assert fleet.recompute_worker_native("w", rec, [LIVE_SHAPE])["status"] == "idle"   # status: IDLE
```

MEASURED. `fleet respawn` refuses with *"turn is running"* on a worker the status table renders as
`idle`. **Neither reader is wrong about its own question.**

A second, sharper divergence is **latent**: `recompute_worker_native:3760` re-spells roster
liveness inline as key-presence **alone**, with no `state != "done"` clause at all. On a
`{state:"done", status:"busy", pid:N}` entry, `_roster_live_sids` returns `set()` (dead) and
`recompute_worker_native` returns `working`. MEASURED as a code divergence; **zero instances on
this win32 roster**, and BELIEVED reachable on posix per `_roster_live_sids`'s own 2026-07-19
macOS finding.

> **A near-miss worth recording.** The first draft of these tests built timestamps with
> `datetime.isoformat()`. `fleet._parse_iso` is a bare `strptime("%Y-%m-%dT%H:%M:%SZ")` and raises
> on the offset form — which `_launch_claim_expired` swallows into *"not expired"*. Every
> recompute test would have passed **through the dispatch-grace branch instead of the branch it
> named**: green, for the wrong reason. The tests now assert `_dispatch_grace_active(rec) is
> False` before relying on a roster branch, and the `working` case is discriminated by flipping
> the roster `status` to `idle` and requiring `dead-suspected`.

### 4.2 Disagreement 2 — MECHANISM REPRODUCED ✅, INCIDENT NOT ATTRIBUTED ⚠️

MEASURED, with the control run first:

```
CONTROL (roster fetch OK):     finished={'lane': 'idle'}, pending=set()
FREEZE  (roster fetch fails):  finished={},               pending={'lane'}
```

Same worker, same roster content, same instant — the only change is that `_fetch_agents_roster`
reports failure. The verdict is not delayed; **it is never computed.** And the freeze also fires on
a roster that exits 0 with `[]` (`roster_ok` is `True`, so nothing looks broken), which is the
shape most likely to bite in practice — MEASURED, with both control limbs (a non-empty roster does
not freeze; an empty roster with no `working` record does not freeze either, proving the predicate
reads the registry and not merely the roster's emptiness).

**I did not confirm this is the incident's mechanism.** See §1's caveat. Reporting it as
"disagreement 2 confirmed" would be exactly the unreceipted claim the brief forbids.

### 4.3 Disagreement 3 — REPRODUCED ✅, and it is not a bug in any reader

MEASURED — **nothing in the tree ever converts heartbeat age into deadness.**
`_supervisor_tier_snapshot` returns `state:"held"` at a 40-minute-stale beat and at a
400-hour-stale beat alike. The watcher supplied the inference.

MEASURED — **the projection it read has four keys and none is about a process**:
`{goals_active, state, incarnation_id, heartbeat_age_seconds}`. There is nothing there for a
correct watcher to key on. And the code already *says* so, in a place the watcher could not see:
`_supervisor_tier_snapshot`'s own docstring — *"`state` is the CLAIM's state, not a body's
liveness."*

MEASURED — **a busy supervisor and a dead one produce byte-identical projections**
(`test_a_busy_supervisor_and_a_dead_one_are_the_same_snapshot`).

MEASURED — **the cost asymmetry runs the opposite way from the watcher's**. The same stale beat
that made the watcher say "dead" silently **disarms `_supervisor_gate`** (`:15624` — `if age >
SUPERVISOR_CLAIM_STALE_SECONDS: return  # stale: disarmed`), and `clean` is a gated verb
(`:9726`). The watcher's false-dead cost one wasted intervention. The disarm makes
`fleet clean --yes` reachable from a third body.

**Credit where it is due: the disarm is NOT my discovery and I will not present it as one.** It is
disclosed in `_supervisor_gate`'s own docstring and was ratified by council as a known price of
option (b): *"a DISCLOSED weakness of option (b), not a bug."*

**What IS new is that the ratification's stated model of the risk window is wrong, and this
incident is the counter-example.** The docstring justifies the disarm as leaving protection
*"present only in the hour after a human last acted and absent in the quiet stretches an
unattended second body would exploit."* That reasoning assumes beat-staleness tracks *inactivity*.
MEASURED, it does not: **`heartbeat_at` refreshes only on `sup-*` verbs (§2.4), and a supervisor
doing forty minutes of `git` and `pytest` is the busiest it ever gets while emitting none.** So the
gate disarms *during heavy supervisor work*, not only during quiet stretches — the opposite of the
window the ratification reasoned about.

**I am filing this, not fixing it.** It is a supervisor-gate finding, not a liveness-reader one,
and folding it into this slice would widen it past what §5 rules on (§5.5). But the successor
should know that "beat age = supervisor inactivity" is a premise two separate mechanisms now rest
on, and it is false.

---

## 5. THE RULING (deliverable C)

### 5.1 One canonical *verdict* cannot serve every reader. One canonical *value* can, and should.

The brief asked whether one canonical answer serves everybody. **The answer splits on what
"answer" means, and getting that distinction wrong is how this fix goes wrong**, so I am stating
it before the ruling rather than after.

I walked all 11 `_roster_live_sids` sites plus the 6 other readers in §2.3. A single **binary
verdict** — the alive/dead each caller acts on — fails immediately on cost asymmetry:

* `cmd_clean` must **spare** when the roster is unreadable; a false dead deletes a live worker's
  journal, irreversibly.
* `fleet status` must **guess** in the same situation; refusing to guess *is* disagreement 2,
  which is the thing we are trying to fix.

Opposite requirements, same input. No binary value satisfies both.

**But a single canonical tri-state VALUE satisfies both trivially**, because `LIVE / GONE /
UNKNOWN` lets each reader keep its own mapping: `clean` maps `UNKNOWN → spare`, `status` maps
`UNKNOWN → guess`. That is not a compromise — it is the correct factoring, and it is what §6
builds. **The measurement of the fact is shared; the policy on ambiguity is per-reader and
stays per-reader.**

So the ruling is not "they cannot share". It is: **they can and must share the value for Q1, they
must not share a verdict, and Q2 and Q3 are different questions that cannot share either.** Three
questions, three genuinely different cost asymmetries — the split is **CORRECT rather than merely
current**. But — and this is the ruling, not a description — **the split fleet has today is not
that split.** Three questions, four-and-a-half implementations, no stated mapping:

| the question | what SHOULD answer it | what actually answers it today |
|---|---|---|
| **Q1 — is a body running?** (process) | one named tri-state predicate | `_roster_live_sids` (11 sites) **+** each caller's own `if not roster_ok` **+** `recompute_worker_native`'s inline half-copy at `:3760` |
| **Q2 — is this worker mid-turn?** (turn) | one named predicate over Q1 + `status` value | `recompute_worker_native`, unnamed, inlined, 11k lines from Q1 |
| **Q3 — did the supervisor recently act as supervisor?** (duty) | `heartbeat_at`, unchanged | `heartbeat_at`, correctly — **and it is also being read as Q1, which it cannot answer** |

**Verdict: three readers because three genuinely different questions — a sound design that needs
documenting and pinning — with ONE genuine defect inside it: Q1 is spelled three times, and Q2 is
not named at all.** Not "nobody unified them". The line is drawn there.

### 5.2 `state:"done"` — a fact about the process or about the turn? **NEITHER.**

The brief offered two options. MEASURED, the answer is a third: **`state` is a fact about how the
last RUN ended, and it outlives both the process and the turn.** 69 `done` entries and 60 keyless
not-`done` entries persist for hours after their processes are gone. The three facts are in three
fields (§0's table).

So the `state != "done"` clause in `_roster_live_sids` is **a process question answered with a
run-fact field** — which is precisely why it is inert on win32 (where key presence tracks the
process faithfully) and load-bearing on posix (where the process lingers, key presence stops
moving, and the run-fact is the only thing left that has). *The clause is a correct patch for a
platform where the process fact is unreliable.* It should be documented as that, and it should
apply to `stopped`/`failed` too — **BELIEVED, not measured; I have no posix roster.** Flagged in
§6 as the one thing the build must measure on posix before shipping.

### 5.3 Does a "we do not know" third value belong? **YES for Q1 — and it already exists,
spelled twice.**

MEASURED: every Q1 caller already implements a tri-state. `_roster_live_sids` returns the LIVE
set; the `roster_ok` flag carries UNKNOWN; and each of the 11 callers re-derives what UNKNOWN means
for it — `:8225` refuses, `:9408` refuses, `:9766` spares, `:15459` fails open, `:18551` reports
`True` with a caveat. **The third value is not a new concept. It is an existing concept that is
returned out-of-band and re-interpreted 11 times.** Making it the return value is a
consolidation, not a new state.

**And that is why it does not need a clearing ritual.** The brief's warning is exactly right about
`dead-suspected` — *a signal nobody is obliged to act on stops being a signal*, and five husks
reached 234h proving it. **The distinction that makes UNKNOWN safe is: `dead-suspected` is
PERSISTED to the registry and accumulates; Q1's UNKNOWN is COMPUTED PER CALL and never written.**
It cannot accumulate because it has no storage. Its "clearing ritual" is the next roster fetch.

**I therefore reject a persisted indeterminate state anywhere in this design,** and §6's build
brief includes a mutant that plants one, so the guarantee is proved rather than asserted.

### 5.4 Does `heartbeat_at` want a second liveness channel, or the watcher's question changed?

**REJECTED: bolting process-existence onto `heartbeat_at`.** The heartbeat means *"a supervisor
verb ran recently"* and `_supervisor_gate` depends on exactly that meaning to decide whether a
claim is stale. Widening it to *"or the process exists"* would keep the gate armed against a
supervisor that has stopped supervising — a live-but-wedged body would hold the fleet's mutating
verbs hostage indefinitely. **The heartbeat is right. Do not touch it.**

**PARTLY ACCEPTED: the watcher's question was wrong.** *"Did the supervisor recently act as a
supervisor?"* is a fine thing for a **gate** to ask. It is the wrong thing for a **watcher** to
ask, because the watcher's remedy (declare it dead, intervene) is only correct for a body question.

**But "the watcher was wrong" is not a sufficient ruling, and I will not leave it there.** The
watcher had no correct alternative. MEASURED: both supervisor surfaces are file-only by mandate
(`cmd_sup_status`: *"no lock, no probe, no write"*; `_supervisor_tier_snapshot`: *"no roster read,
no probe, no subprocess"*), and terminal-surface D1/D4 forbid a view probing. **The supervisor tier
is structurally incapable of answering "is the body alive", and telling the watcher to ask a
better question without giving it one is how you get the same incident again with a different
field.**

**RULING: the watcher's question changes AND it gets a surface — but the surface is a VERB, not a
view.** `fleet sup-status --probe` (opt-in, fetches the roster, prints the holder sid's Q1
tri-state). The views keep rendering the beat age and keep saying nothing about liveness. This
respects D1/D4 exactly: a view never probes; an operator who asks explicitly gets a probe. And
the doctrine sentence that already exists in `_supervisor_tier_snapshot`'s docstring gets promoted
to somewhere a watcher-author reads it — `docs/specs/terminal-surface.md`.

### 5.5 What I am NOT proposing

* **Not** unifying Q1 and Q2. §5.1's asymmetry table forbids it.
* **Not** touching `heartbeat_at`'s semantics or `_supervisor_gate`'s staleness disarm. §5.4.
  (The disarm is council-ratified and disclosed. What §4.3 files is narrower and new: the
  ratification's premise that beat-staleness tracks *inactivity* is false, because a merging
  supervisor is maximally busy and emits no beat. That is a *supervisor-gate* finding, not a
  liveness-reader one, and folding it in here would widen the slice past what §5 rules on.
  **Filed, not fixed.**)
* **Not** removing the epoch freeze. §1. It gets a *surface*, not a change.
* **Not** deleting the `state != "done"` clause, however inert it measures on win32. §5.2.

### 5.6 Is it cheaper to live with?

**No — and the honest reason is not the wall-clock.** BELIEVED: the wave-time cost of
disagreements 1 and 2 is minutes per wave, which alone would not clear the "self-repair only when
it blocks the axis" bar. **MEASURED (I read all 11), what clears the bar is that 9 of the 11 Q1
call sites gate an operation whose false-dead branch is unrecoverable** — `clean` deletes journals,
`respawn` can produce two live sessions under one name, `archive` can delete the state the wedge
gate reads, `sup-boot` can seize a live claim. The two exceptions are display-only
(`_render_boot_bundle` `:15180`, `_doctor_check_supervisor_wedge` `:18559`), and §2.2's table names
which is which. Those 9 sites are correct *today* because their callers independently re-derived
the same conservative interpretation of an out-of-band UNKNOWN. **That is not a property anybody is
enforcing; it is nine coincidences.** The tenth caller is the defect, and
`recompute_worker_native:3760` is already a half-instance of it — a Q1 predicate re-spelled without
the clause its author called load-bearing.

The fix is ~80 inserted lines at a **measured** cost of **7 re-pins** (§6.5). At that price it is
cheaper to fix than to keep re-deriving.

---

## 6. BUILD BRIEF FOR THE SUCCESSOR (deliverable D)

Executable on a settled `bin/fleet.py` without re-deriving anything above.

### 6.1 Files

| file | change |
|---|---|
| `bin/fleet.py` | one new function + one new `sup-status` flag; 11 call sites re-pointed; 1 docstring corrected. **Insertion point is not free — see §6.5.** |
| `tests/test_liveness_readers.py` | **exists on `w50/live`.** Invert the 7 `INVERT-ON-BUILD` tests. |
| `docs/specs/native-substrate.md` | add the §0 three-facts table to the roster contract. |
| `docs/specs/terminal-surface.md` | new clause: a view never answers Q1; `sup-status --probe` is the verb that does. |

### 6.2 The predicate

```python
# INSERT IMMEDIATELY BELOW `_roster_live_sids` (currently :14656) -- NOT near
# `recompute_worker_native`. See the re-pin measurement in the w50-live report §6.5.

ROSTER_LIVE, ROSTER_GONE, ROSTER_UNKNOWN = "live", "gone", "unknown"

def roster_body_state(roster_ok: bool, entries, sid: str) -> str:
    """Q1 ONLY: does a host process for `sid` exist? Tri-state, and UNKNOWN is
    a real answer, not a failure -- every caller today re-derives it from an
    out-of-band `roster_ok` flag, 11 times, and they agree by coincidence.

    NEVER PERSISTED. Computed per call, never written to the registry. That is
    what distinguishes it from `dead-suspected`, which accumulates and reached
    234h across five husks because no ritual clears it. This value's clearing
    ritual is the next roster fetch, which is to say it has no lifetime at all.

    This answers NOTHING about the turn. `status`'s VALUE is the turn fact and
    `state` is the last-RUN fact; conflating them is the w50 finding."""
```

Body: `if not roster_ok: return ROSTER_UNKNOWN`, then the existing
`_roster_live_sids` membership test, unchanged, on `entries`.

**`_roster_live_sids` stays.** It keeps its 11 call sites and becomes a thin wrapper — the union
arm in `_releaser_live_sids` needs the *set*, not a per-sid verdict, and re-keying that is a
different slice (its docstring's fork-steer boundary argument is load-bearing and must not be
disturbed).

### 6.3 Call-site changes

1. **`recompute_worker_native:3760`** — replace the inline `live = entry is not None and (...)`
   with `roster_body_state(...) == ROSTER_LIVE`. This closes the latent third spelling. *Then
   re-read §5.1: `status` must stay liberal, so on `ROSTER_UNKNOWN` it takes the
   `has_fresh_outcome` path exactly as it does today for a roster-gone sid. Do not make it
   conservative.*
2. **The 9 non-display Q1 sites** — replace `if not roster_ok: <...>` +
   `sid in _roster_live_sids(...)` with a single `roster_body_state(...)` switch.
   **Each site keeps ITS OWN mapping — do not give them a shared one.** Per §2.2's policy table:

   | sites | `ROSTER_UNKNOWN` maps to |
   |---|---|
   | 1–5, 7, 9 (`respawn` ×2, `archive`, `sup-boot`) | the `ROSTER_LIVE` branch — refuse/freeze |
   | 6 (`clean`) | the `ROSTER_LIVE` branch — spare |
   | **10 (`_wedged_release_gate`)** | **the `ROSTER_GONE` branch — fail OPEN, unchanged** |

   Site 10 is the trap. It reads like the others and it is not: making it conservative would arm
   the gate on every transient roster failure and refuse **every mutating verb fleet-wide**. Its
   own docstring gives the reason (*"a speed-bump must not brick every mutating verb"*). A
   successor who "unifies" the UNKNOWN policy here has introduced an outage, and the test in §6.4
   M2 is written to catch exactly that. **Behaviour must be byte-identical at all 9 sites; the
   coincidence becomes a property, and nothing else changes.**
3. **`cmd_sup_status`** — add `--probe`. Without it, byte-identical output (D1/D4 hold).
4. **`_roster_live_sids`'s closing parenthetical** — replace with §3.5's wording.
5. **`_roster_entry_has_life_signal`** — add one sentence: *"This is NOT Q1. It answers 'did this
   session ever attach', and on the 60 keyless terminal entries measured 2026-08-09 it returns
   True where `roster_body_state` returns GONE. Both are correct."*

### 6.4 Tests that must go RED first, and the mutants that prove them

| # | test (RED first) | mutant that must make it RED |
|---|---|---|
| M1 | `roster_body_state` returns `ROSTER_UNKNOWN` on `roster_ok=False` | `return ROSTER_GONE` on the failure arm |
| M2 | **each Q1 site keeps the UNKNOWN mapping §6.3 assigns it — per site, not in aggregate** | two mutants, both required: (a) flip **one** conservative site's UNKNOWN branch to proceed; (b) flip `_wedged_release_gate`'s UNKNOWN branch to *arm*. The test must name *which* site each time — an aggregate assertion passes on the other 8, and (b) is the one a "unify the policy" refactor introduces |
| M3 | `recompute_worker_native` still reaches `has_fresh_outcome` on UNKNOWN | make it conservative → the test must go RED, proving Q2 stayed liberal |
| M4 | `roster_body_state` is never persisted | write it into `new_worker_record`'s schema; a grep-based test is **not** sufficient — assert `state/fleet.json` bytes carry no such key after a full status/wait/clean cycle |
| M5 | the `done`-clause deletion is caught | delete `and e.get("state") != "done"`. **This mutant SURVIVES on win32 today** (§3.3) — the test must use a synthetic posix-shaped entry, and this is the mutant most likely to be declared "unreachable" and skipped. It is the whole reason the clause is there. |
| M6 | `sup-status` without `--probe` performs no subprocess | make the non-probe path fetch the roster; assert via a `run=` seam that records calls, not by timing |
| M7 | the 5 `INVERT-ON-BUILD` tests fail if the readers are *not* unified | revert one call site |

**Also carry forward, unchanged:** `test_a_released_claim_has_no_beat_and_that_is_not_staleness`.
A released claim's `heartbeat_age_seconds is None` means *correct stand-down*, never *stale*; any
canonical answer must keep saying so. That lesson is already paid for.

### 6.5 Self-citation cost — MEASURED, not inherited

Wave 47 measured 37 inserted lines → 32 re-pinned citations. **That ratio is not a constant; it is
entirely a function of WHERE the insert lands,** because only citations *below* it move. Measured
against this tree (36 enforced self-citations in `bin/fleet.py`, controls at both ends of the
range: insert@0 re-pins all 36 `PASS`, insert@EOF re-pins 0 `PASS`):

| insertion point | self-citations re-pinned |
|---|---|
| next to `recompute_worker_native` (`:3714`) | **26 of 36** |
| next to `_roster_live_sids` (`:14656`) | **7 of 36** |
| next to `cmd_sup_status` (`:16779`) | **2 of 36** |

**Estimate: ~80 inserted lines (≈45 predicate + docstring, ≈20 `--probe`, ≈15 across call sites),
landing at `:14656` and `:16779`, for ~7–9 re-pins.** Placing the same code near
`recompute_worker_native` would cost ~26 — nearly 4× — for no design benefit. **Insert low in the
file and re-point upward.** Re-pin FORWARD in the same commit and warn the supervisor, per the
day-5 lesson.

---

## 7. WHERE THIS BRIEF WAS WRONG

| # | the brief's claim | verdict |
|---|---|---|
| 1 | "These are three instances of one class" | **PARTLY WRONG.** #1 and #3 are one class. **#2 is not** — it is a correct, deliberate safety freeze whose only defect is silence. Unifying it would produce a wrong fix. §1. |
| 2 | "The `_roster_live_sids` Windows parenthetical is the cause of disagreements 1 and 2" | **WRONG, and the premise under it did not reproduce.** MEASURED: 0 done-with-keys entries in 137. The parenthetical is false for a *different* reason (60 reverse counter-examples), and the entry that actually splits the readers is `blocked`, not `done`. §3, §4.1. |
| 3 | "`heartbeat_at` refreshes only on `sup-*` verbs" | **RIGHT.** MEASURED: 8 write sites, all in `cmd_sup_*` functions bound to `sup-*` verbs; no hook writes it. §2.4. |
| 4 | "10 call sites, counted by grep" | **WRONG, and in the direction the brief did not guess.** MEASURED: **11**. Grep's 14 = 11 calls + 1 def + 2 docstring mentions. The brief expected the grep to over-count; it under-counted. §2.2. |
| 5 | "A read-only lane can settle this" | **RIGHT.** Every finding here is a pure-function or AST measurement plus one read-only vendor roster fetch. No production change was needed to reach the ruling, and no live fleet verb was run. |

**A sixth, which the brief did not list.** It named five readers to start from and asked me to go
beyond them. The one that most sharpens the finding is `_roster_entry_has_life_signal` — a shipped
predicate that returns **the exact opposite** of `_roster_live_sids` on one-third of the live
roster (§2.3). A census that had started and stopped at the named five would have missed the
clearest evidence that "liveness" is not one question.

**And a seventh, about my own work — three defects, and the third is the one to weigh.**

1. My first heartbeat census reported **5** writers. There are **8**: `ast.Dict` keys are not
   `ast.Subscript` stores. Caught by a reconciling control, not by review; the control is now in
   the test file.
2. My first timestamp fixtures were unparseable by `_parse_iso`, which would have made the
   recompute tests green **through the dispatch-grace branch instead of the roster branch they
   name** (§4.1). Caught by a failing assertion, then guarded by `_grace_is_shut`.
3. **My first draft of §2.2 asserted that *"every one of these callers already refuses on an
   unfetchable roster or spares on an unknown one"*. That was a generalisation from the first two
   sites, and it is false.** `_wedged_release_gate` (`:15459`) **fails OPEN** on an unreadable
   roster — deliberately, because it runs at the top of every mutating verb. I found it only
   because I went back to read all eleven rather than trusting my own table.

The first two were defects in the measuring apparatus. **The third was a defect in the reasoning,
it survived my own census, and it would have shipped a build brief that told the successor to make
that gate conservative — arming it on every transient roster failure and refusing every mutating
verb fleet-wide.** §6.3 now names it as the trap and §6.4 M2(b) is the mutant for it. *The lesson
this lane keeps re-teaching itself: an enumeration you generalise from is an enumeration you have
not done — which is the brief's own "inherited enumeration smaller than reality", committed by the
person writing the census.*

---

## 8. SAFETY — exactly what I ran

**Live fleet verbs run: NONE.** Not `status`, not `peek`, not `result`, not `doctor` — the brief
permitted those four and I did not need any of them. Every reproduction is a pure-function test.

**The one live read:** `claude agents --json --all`, once, captured to a file outside the repo.
That is the vendor CLI's own read-only listing. It takes no `fleet.lock`, reads no fleet home,
and is the same command `_fetch_agents_roster` shells out to.

* No `fleet init`, no `FLEET_HOME` set or exported, no `--fleet-home` passed (no fleet verb ran at
  all).
* `~/.claude/settings.json` and `~/.claude/fleet-homes.list` never opened for write.
* Test runs are sandboxed by `tests/conftest.py`'s autouse fixtures; the session-scoped
  code-plane hash guard passed on both interpreters.
* Nothing that matters lives under `state/` — this report is committed at `docs/lanes/w50-live.md`
  and the tests at `tests/test_liveness_readers.py`. `state/journals/w50-live.md` holds working
  state only.
* Branch `w50/live` only. No push, no merge, no other ref moved. `bin/fleet.py` byte-identical.
