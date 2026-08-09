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
(reasoning, or documentation I did not execute).

> ## REVISION 2 — after the `w50/glive` gate (`ffaad73`), which GATED this branch
>
> **My headline was wrong and the gate was right.** Revision 1 led with *"the predecessor's
> measurement does not reproduce"*. It reproduces. The gate found one counter-example; I
> re-measured with a method that can actually see the shape and found **three at once, one of
> them a session that was executing a turn at the time.**
>
> **The error was not a miscount — it was an inference from a single snapshot**, and §3 now
> carries it as the lane's own methodology lesson rather than as a footnote.
>
> What survived attack, per the gate's own §5, and is therefore *not* re-argued below: the
> **field-conflation diagnosis** (F1 strengthens it), the **11-site census**, the **heartbeat
> census**, **poll-not-push**, both **floors**, and the **fence**. Sections rewritten for the
> gate's findings are marked **[REV2]**. Findings I am contesting: **§9** — one, partially.

---

## 0. HEADLINE

**MEASURED [REV2] — the roster's `state` field can be wrong about a session that is actively
working, and that is the sharpest form of this lane's whole thesis.** A detached sampler (29
samples, 20s apart, ~10 minutes, run from a process outside every session it observed) found
**three sids simultaneously** carrying `state:"done"` **with** `pid` and `status:"idle"` — and one
of them was **this lane's own session, mid-turn, for all 29 samples**, pid verified alive.

**So the predecessor was right and my refutation was wrong.** *"On Windows the two conditions
agree — done entries lose pid/status"* is false on win32, in the direction originally claimed.
It is **also** false in the reverse direction (60 counter-examples: `blocked` ×32, `stopped` ×26,
`failed` ×2). Both halves of the biconditional fail. §3 has the receipts and the post-mortem on
how I got zero honestly.

**What does NOT follow, and I will not swing to it:** the brief's *causal* claim — that the
parenthetical explains disagreements 1 and 2 — is still not established. §3.4 and §4.1 measure
that the entry which splits `respawn` from `status` is `blocked`, not `done`. The parenthetical
is a false comment sitting above a clause that is genuinely load-bearing; the disagreement it was
blamed for has a different cause. **Two separate defects in the same six lines.**

**MEASURED — the real cause of disagreement 1 is a field conflation, and it is live in the roster
right now.** The roster carries **three different facts in three different fields**, and
`_roster_live_sids` answers a question about one of them using another:

| roster field | the fact it states | evidence |
|---|---|---|
| `pid` / `status` **key presence** | **a host process exists** | **MEASURED: 8/8 keyed entries back a live OS process** at t0, and the gate independently measured 9/9 later (`tasklist` per pid, control limbs both passing). The converse (keyless ⇒ gone) is **BELIEVED**, not measured: a keyless entry carries no pid to check. **This is the only one of the three fields never measured wrong.** |
| `status` **value** (`busy`/`idle`/`waiting`) | *intended:* the current turn | **[REV2] MEASURED WRONG.** Read `idle` for 29/29 samples on a session that was executing a turn throughout. |
| `state` (`working`/`done`/`stopped`/`failed`/`blocked`) | *intended:* how the last RUN ended | **[REV2] MEASURED WRONG in the same window** — read `done` for the same executing session. It also outlives the process (129 of 137 entries carry a `state` and no process keys), so it is not a process fact either. |

`_roster_live_sids` asks a *process* question (`is a body running?`) and answers it with key
presence **plus a `state` clause** — a run-fact. `recompute_worker_native` asks a *turn* question
and answers it with key presence **plus the `status` value**. On the same entry
(`state:"blocked"`, `status:"idle"`, `pid:38336` — a real supervisor, in the roster as I write
this, and **MEASURED to be a live OS process**) reader A says **LIVE** and reader B says **IDLE**.
That is disagreement 1, and it contains no `done` entry at all.

That entry is worth pausing on, because it is the whole finding in one row: the process **is**
alive (so reader A is right), its turn **is** over (so reader B is right), and its last run ended
`blocked` (so the field reader A consults is talking about neither).

**[REV2] And the `done`-with-keys entries are the same finding, one notch worse.** There, `state`
is not merely talking about something else — it is *wrong about the thing it names*. On such an
entry `_roster_live_sids` returns **not-live for a live, working process**, so `fleet respawn`
does not refuse and proceeds to stop it. That is the **false-DEAD** direction, which §2.2 shows
is the unrecoverable one at 9 of 11 sites. Driven, not argued:
`TestTheShapeABusySessionActuallyPresents`, three tests including the control that shows the
identical call *does* refuse once the same entry reads `working`/`busy`.

**THE RULING (§5): one canonical *verdict* cannot serve every reader; one canonical tri-state
*value* can, and should.** The split is **CORRECT rather than merely current** — three genuinely
different questions with three genuinely different cost asymmetries — **but the split fleet has
today is not that split.** There are **five-and-a-half** implementations (`_record_is_live` is the
fifth — §2.5, found by the gate) spread across those three questions with no stated mapping. The
defect is not that there are three readers; it is that **only one question has a named
predicate**, so the other two are answered by whichever field is nearest, and the one ambiguity
value every reader needs (`UNKNOWN`) is passed out-of-band and re-interpreted at every site.

**Verdict on the brief's framing question:** disagreements 1 and 3 are the same class (a reader
answering its question with the nearest available field). **Disagreement 2 is a different class —
a deliberate, correct safety freeze with no surface — and unifying it with the other two would
produce a wrong fix.** [REV2] **That classification is asserted with LOW confidence about the
incident it explains:** I reproduced a mechanism that produces the symptom, but I could not
attribute the actual incident to it, and a second mechanism (poll-not-push) fits equally well.
§1's caveat is the binding statement and this line must not be read as stronger than it. If the
incident was mechanism 2, a surfaced freeze fixes nothing and the wave will read as having closed
disagreement 2 anyway — so §6 now carries an attribution step, not just a surface.

**Is it worth fixing? YES, and it is cheap, but not where you would put it.** MEASURED: the
insertion point dominates the cost — next to `recompute_worker_native` (`:3714`) re-pins ~4× what
`_roster_live_sids` (`:14656`) does. §6.5 gives the numbers *with the population that produced
them*, after the gate showed my first figures were unreproducible without it.

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

**MEASURED asymmetry — and it is NOT uniform, which is the more useful finding.** [REV2] For
**eight** of the nine non-display sites a false *dead* is unrecoverable and a false *alive* is a
recoverable refusal. **Site 10 (`_wedged_release_gate`) is the exception and it runs the other
way**: its false-*alive* cost, in the table below, is *"every mutating verb refused fleet-wide"* —
which §6.3 calls an outage, not a recoverable refusal. Revision 1 stated the asymmetry over all
nine here while retracting it in §7 and carving site 10 out in §6.3; the gate (F2) found the
retraction recorded in one section and contradicted in three others. The carve-out is now stated
everywhere the generalisation is.

I checked all 11 rather than generalising from the first two:

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
| **[REV2] `_record_is_live` `:2993`** (3 call sites) | `isinstance(rec, dict) and rec.get("archived_at") is None and rec.get("status") != "dead"` | **could this record BE an acting body?** — Q1, **from the REGISTRY** | false-live manufactures an AMBIGUOUS identity verdict; false-dead strands a real body's identity |

**`_roster_entry_has_life_signal` is the reader the brief did not name, and it is the sharpest
one.** MEASURED: it returns **`True`** where `_roster_live_sids` returns **`set()`** on
**131 of 139** entries — every `done` (71), `failed` (2), `stopped` (26) and keyless `blocked`
(32). [REV2] Revision 1 said *"60 of 137"* and *"one-third of the live roster"*: that reused the
reverse-counter-example population from §3.2 and left out the 71 `done` entries, which disagree
too. **The real figure is ~94%, and my own test always asserted the wider property** — the loop in
`test_life_signal_and_roster_live_are_exact_opposites_here` iterates `("done", "failed",
"stopped", "blocked")`. The prose narrowed what the test proved (gate F9). Both readers are still
right: one asks *"did this ever attach"*, the other *"is it running now"*. Nothing in the tree
says so.

### 2.5 [REV2] `_record_is_live` — the reader the gate found, and why it changes the build

**MEASURED.** Found by the `w50/glive` gate (F5), absent from revision 1's census entirely. It is
a shipped Q1 predicate that reads the **registry** rather than the roster, with three call sites:
`_acting_worker_identity:3156`, `_releaser_body_is_tombstoned:14815`,
`_tombstone_releasing_body:16534`.

Its whole body is *"not archived, and status is not `dead`"*, so **every other status reads as
live** — and that puts it in direct contradiction with the Q2 reader on the same record in the
same process:

```
recompute_worker_native(record, roster=[])  ->  "dead-suspected"   (no roster entry, no outcome)
_record_is_live(that same record)           ->  True
```

`recompute_worker_native` demotes a record precisely because it could find no life for it;
`_record_is_live` reads the demoted record and calls it live. Pinned by
`TestTheThirteenthReader`, three tests with both control limbs (`status:"dead"` → False, archived
→ False, non-dict → False).

**It lands squarely on §5.3's own argument.** The five `dead-suspected` husks that reached 234h —
this report's example of a signal nobody is obliged to act on — are `live` to this reader for
every one of those hours.

**And it is why §6.2's first draft was wrong.** That predicate was
`roster_body_state(roster_ok, entries, sid)`: roster arguments only, no registry argument, no
place for this reader. `_record_is_live` reaches `_wedged_release_gate` — the site this report
warns hardest about — through `_releaser_live_sids`'s tombstone arm. **Build §6 as first specified
and a fifth spelling of Q1 survives the consolidation, inside the trap.** §6.2 is re-specified.

**I am not claiming the population is now closed.** Revision 1 asserted closure by omission; this
one asserts it nowhere. `test_the_reader_population_is_not_asserted_closed` sweeps for
liveness-shaped names and forces each into the census or an explicit exclusion list — it caught
two more on its first run (`_any_live`, a real Q1 reader nested in `_cmd_respawn_supervisor`; and
`_multi_fleet_population_is_live`, a **false positive** — "live" there means a live population of
fleet *homes*). That the sweep produces false positives, and that `_dispatch_grace_active` is a
genuine reader carrying none of the tokens, is exactly why a name sweep **cannot** be the closure
argument, and the test says so in its own docstring.

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

## 3. THE WINDOWS PARENTHETICAL — **[REV2] rewritten; revision 1 was wrong here**

```
    (On Windows the two conditions agree -- done entries lose pid/status.)
```

### §3.0 — THE MEASUREMENT THAT REPLACES REVISION 1'S, AND WHY IT IS DIFFERENT

Revision 1 took **one snapshot from inside a session that was itself running the measurement**
and generalised it. That is the defect, and it is a methodology defect rather than a counting
error: **a session executing a measurement is `busy`, so its own entry cannot exhibit a
turn-end shape at the moment it looks.** If every other session on the box also happens to be
mid-turn — which is what a wave of parallel lanes looks like — the shape is absent from the
snapshot and present in the world. My detector control was correct and passed; **a control
proves the detector can see the shape, and licenses nothing about whether the window was
sampled.**

The replacement observes **from outside**: a detached `Start-Process` sampler (PID 43584), not a
claude session, polling `claude agents --json --all` every 20s. Every session in the roster is
therefore external to the observer, and the run spans minutes rather than an instant.

```
samples: 29  from 2026-08-09T06:04:33Z to 2026-08-09T06:14:xxZ   roster: 141 entries

CONTROL positive limb: 2 (expect 2) PASS      <- shaped synthetic, done-with-keys
CONTROL negative limb: 0 (expect 0) PASS      <- same roster with the done entries removed

Q-A  distinct sids observed as state='done' WITH pid/status keys: 3
       93f5c952  seen in 29/29 samples, status='idle' pid=41464
       b9b2124d  seen in 29/29 samples, status='idle' pid=4436
       2d3724ff  seen in 29/29 samples, status='idle' pid=38740

Q-C  the OBSERVING session's own entry (b9b2124d), every sample:
       state=done  status=idle  pid=4436   samples 1-29 (29x)
       pid 4436 alive now: True   (control: bogus pid alive = False, expect False)
```

**`b9b2124d` is this lane's own session, and it was executing a turn for the entire window** —
the sampler was launched from inside that turn and every one of these tool calls ran during it.

The run also carries a **licensing control the first measurement lacked** (Q-B): it reports
whether any session was observed in more than one phase, because without a phase transition
somewhere in the window, a zero in Q-A would again be indistinguishable from "nothing finished
while I watched". **Q-B reported 0 transitions in this window.** Q-A is non-zero so nothing here
rests on it — but it is now impossible to report a zero from this harness without the reader
being told the window was uninformative.

### §3.1 — [REV2] The predecessor's measurement REPRODUCES. Mine was the wrong one.

MEASURED: three concurrent counter-examples, each stable across 29 consecutive samples. The
forward direction — *`done` ⇒ no keys* — is **FALSE on win32**, exactly as
`_roster_live_sids`'s docstring records from macOS on 2026-07-19. Revision 1's §3.1 asserted the
opposite and five further sections descended from it.

**One thing measured here goes past both the predecessor's claim and the gate's**, and it is the
finding I would keep if I could keep only one: the entry was not a *lingering finished* session.
It was **mid-turn**. `state` said `done` and `status` said `idle` about a session that was
actively working. So the parenthetical is not just stale — the field it describes is not
reliably reporting what its own name says even for live sessions.

**Mechanism: BELIEVED, not measured.** The likeliest account is that `state` flips to `done` at
turn end and is *not* flipped back when a subsequent turn begins in the same session — the three
affected sids are all sessions on a later turn, while the sessions still on their first
dispatched turn read `working`/`busy`. I could not confirm it: observing my own turn boundary
from inside is impossible, and the fence forbids driving another lane to produce one. **The
discriminating experiment for a successor** is to dispatch a throwaway `--bg` session in a
scratch home, let its first turn end, steer it a second turn, and sample the roster across that
boundary from outside.

**What does NOT follow.** The brief's causal claim — that this parenthetical explains
disagreements 1 and 2 — remains **unestablished**, and §3.4 measures against it. Two defects,
six lines apart: a false comment, and a reader answering a process question with a run-fact.

### §3.2 — The sentence is false in the OTHER direction too

MEASURED (t0 snapshot, 137 entries): **60**
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

**§3.3 — [REV2] The `done` clause is NOT inert on win32. It is the difference between refusing
and proceeding, on a live process.** Revision 1 asserted the opposite, and shipped a test named
`test_the_done_clause_is_inert_on_a_windows_shaped_roster` to say so. **That test is deleted.**
Its replacement, `test_the_done_clause_is_NOT_inert_and_changes_exactly_these_answers`, measures
against a roster of the shape win32 actually presents:

```
with clause   : {'s-live'}
without clause: {'s-live', 's-done-1', 's-done-2', 's-done-3'}
DIFFERENCE    : the three done-with-keys entries
INERT?        : False
```

And the direction is the dangerous one. Each of those three is a **live OS process** that the
clause causes `_roster_live_sids` to call **not-live** — so `fleet respawn` does not refuse. The
gate measured the same thing against the real roster (`with 8, without 9`).

**§3.4 — It is STILL not the cause of disagreements 1 or 2, and this survives F1.** MEASURED
(`test_the_split_survives_removing_the_done_clause_entirely`): the entry that splits `respawn`
from `status` has `state:"blocked"`, not `done`, and splits them anyway. The brief's error #2 was
a *causal* inference, and it remains falsified even though its *premise* has now been vindicated.
**Distinguishing these two is the whole point of §7 row 2's re-tag.**

**§3.5 — [REV2] What the parenthetical SHOULD say (BELIEVED — proposed wording, not shipped).**
Revision 1's proposed wording would have shipped *"this clause is currently inert here"* into
`bin/fleet.py` — a false statement, in the file, one line above the predicate. Replacement:

> *(This is FALSE ON WIN32 in both directions, measured 2026-08-09 on claude 2.1.226 — do not
> restore it. Forward: three sessions were observed simultaneously carrying `state:"done"` WITH
> `pid` and `status:"idle"`, sampled every 20s for ten minutes from outside; all three processes
> were alive, and one was executing a turn at the time. So the clause is LOAD-BEARING here, not
> inert: it is what makes `_roster_live_sids` answer "not live" for those entries, which is the
> conservative answer for a lingering finished session and the WRONG one for a working session
> the roster has mislabelled. Reverse: `stopped`/`failed`/`blocked` entries are keyless too, so
> "not `done`" does not mean "live" — `_roster_entry_has_life_signal` answers the opposite way on
> exactly those. Neither field is a process fact; only key presence is.)*

**§3.6 — [REV2] The lesson, which is new and is the lane's own.** Wave 38 says *run the control
against a known non-zero input before trusting a zero.* I did, and it passed, and I was still
wrong. The missing rule: **a control proves the detector can see the shape; it does not prove the
window contained it.** A measurement whose good answer is zero needs a *second* control — evidence
that the population was observed in the state that would have produced a non-zero. That is Q-B
above, and it is why the sampler reports "no phase transition observed" as a first-class result
rather than reporting a bare zero.

---

## 4. THE THREE DISAGREEMENTS, REPRODUCED (deliverable B)

`tests/test_liveness_readers.py` — **[REV2] 31 tests** (was 20), green on `py -3.13` and
`py -3.10`. Roster literals carry **shapes** measured from the live roster; **they are not
verbatim entries** — `LIVE_SHAPE` in particular splices this lane's own `sessionId` onto another
entry's `state`/`status`/`pid`/`name`, and revision 1 called it verbatim in two places (gate F10).
Harmless to the tests, since any sid works; "verbatim" is the word that stops a reader
re-checking, so it is withdrawn.

**They PASS today.** Each asserts a contradiction that is currently true of shipped code, so a
green run is the receipt that the disagreement exists — not that it is fixed.

**[REV2] `INVERT-ON-BUILD`, reconciled (gate F7).** Revision 1 said *five* in §4, *seven* in §6.1
and *five* in §6.4, and told the reader to check with `grep -c`, which returns a fourth number
because the module docstring mentions the marker too. **The count of marked TESTS is now 7**
(five carried over, plus the two added in REV2), and the check that returns it is:

```
grep -c "INVERT-ON-BUILD" tests/test_liveness_readers.py    # 8 = 7 markers + 1 docstring
```

The report states **7 marked tests** and nothing else states a different number. Where the number
matters — §6.4 M7 — it now says "every test marked `INVERT-ON-BUILD`", so a successor counts them
rather than trusting an integer that can rot.

**[REV2] What these tests are NOT.** Three of the original twenty asserted that a substring was
present in `bin/fleet.py`. The gate planted mutants that broke the properties those tests named
while leaving the substrings in place, and all three survived. They are replaced by driven tests
in §4.4, with the mutants as receipts.

### 4.0 [REV2] FLOOR PREDICTION — written and COMMITTED BEFORE the run

Gate F11 is right that revision 1's "predicted before running" lived only in a gitignored,
mutable journal. This prediction is committed as its own commit *ahead* of the run that tests it,
so the ordering is in `git log`. §9 explains why I still label it BELIEVED rather than MEASURED.

**Predicted, before running anything:**

1. `tests/test_liveness_readers.py`: **31 passed** on `py -3.13` **and** on `py -3.10`.
   **Zero floor delta.** The new tests use only `json`/`ast`/`datetime`/`collections.Counter`/
   `types.SimpleNamespace` and no 3.11+ syntax.
2. Full suite: **the previous 4243 + 11 net new = 4254 passed, 14 skipped, 1 xfailed**, on both
   interpreters. (20 → 31 tests in this file; I add 11 and delete 0 net — one test was replaced
   in place, three were rewritten rather than added.)
3. **The named risk, stated in advance:** the driven tests exercise `cmd_respawn`, `cmd_clean`,
   `cmd_sup_release` and `_supervisor_gate` against a sandboxed home. If any of them leaks state
   into another test file's fixtures, the failure will appear in the FULL suite while this file
   stays green — so a green file with a red suite is the outcome I am specifically watching for.

**If any of these misses, I stop and report it rather than adjusting the prediction.**

### 4.1 Disagreement 1 — REPRODUCED ✅

```python
LIVE_SHAPE = {"sessionId": SID, "state": "blocked", "status": "idle", "pid": 38336,
              "kind": "bg", "name": "sup|inc-c477|boot", ...}   # SHAPE from the live roster,
                                                                # sid spliced -- see above

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

### 4.4 [REV2] The three tests that pinned SOURCE TEXT, and the mutants that proved it

The gate's F3 is the most damaging finding after F1, and it was correct. Three of the original
twenty tests asserted a substring in `bin/fleet.py` or re-implemented an arithmetic identity:

| test | what it actually asserted | mutant that survived it |
|---|---|---|
| `test_respawn_must_stay_conservative_toward_alive` | `"refusing respawn " in src` | a `--force` bypass added **in front of** the refusal — message intact, `respawn --force` now proceeds on an unfetchable roster |
| `test_clean_must_stay_conservative_toward_alive_too` | a **comment** containing the word `SPARES` is present | `... if roster_ok else None` deleted — `clean` DOOMS instead of sparing, comment intact |
| `test_the_gate_disarms_on_the_same_staleness...` | `fresh_age <= STALE < stale_age` — true of any positive constant | the entire staleness disarm deleted |

All three are replaced by tests that **drive the verb and assert the outcome**, each with a
control proving the assertion can go the other way. Re-planted, and the RED watched:

```
FLOOR sha256 : b76dc65d6007ba71e6c59dd47f6ac0502f92588466a22dfd1d1b5a2e4b50ef2c
=== FLOOR (clean tree, no mutant) === rc=0  31 passed in 10.98s

M-A   the stale-beat DISARM of _supervisor_gate is deleted
        -> rc=1  1 failed, 30 passed   ==> KILLED (test went RED)      restored: True
M-B2  respawn gains a --force bypass of the unfetchable-roster refusal
        -> rc=1  1 failed, 30 passed   ==> KILLED (test went RED)      restored: True
M-C   clean DOOMS instead of sparing on an unreadable roster
        -> rc=1  1 failed, 30 passed   ==> KILLED (test went RED)      restored: True
M-D   a Q1 call site relocated out of _wedged_release_gate (decoy keeps the count)
        -> rc=1  1 failed, 30 passed   ==> KILLED (test went RED)      restored: True
M-E   the state != 'done' clause deleted from _roster_live_sids
        -> rc=1  4 failed, 27 passed   ==> KILLED (test went RED)      restored: True

final sha256 == floor: True
real worktree bin/fleet.py untouched: True
```

**All five now KILLED** (M-A/M-B2/M-C/M-D previously SURVIVED; M-E was already killed). Contract
honoured in the driver rather than in prose: `git archive HEAD` scratch export so the worktree's
`bin/fleet.py` is never written, `occurrences == 1` asserted before any run, floor green first,
restore proved by sha256 after every mutant.

**M-D is the gate's F4** — the census pinned `len(calls) == 11` and failed with a message naming
the call sites it could not check. The two-part mutant moved site 10's Q1 read out of
`_wedged_release_gate` and added a compensating call elsewhere: eleven before, eleven after, and
"the trap" no longer reading Q1. The census now pins the **scope multiset**, following
`test_the_heartbeat_census_has_no_hole`, which the gate identified as the strongest test in the
file and the right model.

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
| **Q1 — is a body running?** (process) | one named tri-state predicate | `_roster_live_sids` (11 sites) **+** each caller's own `if not roster_ok` **+** `recompute_worker_native`'s inline half-copy at `:3760` **+ [REV2] `_record_is_live` (`:2993`, 3 sites), which answers the same question from the REGISTRY** |
| **Q2 — is this worker mid-turn?** (turn) | one named predicate over Q1 + `status` value | `recompute_worker_native`, unnamed, inlined, 11k lines from Q1 |
| **Q3 — did the supervisor recently act as supervisor?** (duty) | `heartbeat_at`, unchanged | `heartbeat_at`, correctly — **and it is also being read as Q1, which it cannot answer** |

**[REV2] A fourth question the census forced into the open, and the build must not merge it into
Q1.** `_record_is_live` and `_roster_live_sids` both answer "is this alive", from different
substrates, and they are **not** two spellings of one question:

* **Q1 (roster)** — *does an OS process exist for this sid right now?* Evidence: the roster.
  Volatile, refetched per call, and — F1 — sometimes confidently wrong.
* **Q1r (registry)** — *has fleet retired this record?* Evidence: `state/fleet.json`. Durable,
  written only by fleet itself, and it deliberately does **not** know about processes.

Merging them would be the same error one level up: `_record_is_live`'s callers ask an *identity*
question ("could this record be an acting body, for the purpose of resolving who I am"), and
answering it from the roster would make identity resolution fail whenever `claude agents` does.
**Q1r must keep its own name and its own substrate; what it must NOT keep is the word `live`
unqualified,** because that is what let it into a census of process-liveness readers by
resemblance and out of it by omission.

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

**[REV2] One caveat the gate is right to attach, and I am not going to let it pass as solved.**
The new value does not accumulate — but §6.3 step 1 routes `ROSTER_UNKNOWN` in
`recompute_worker_native` down the `has_fresh_outcome` path, which on a miss reaches
`_investigate_no_outcome` and persists **`dead-suspected`**. So the pipeline still deposits into
the old unbounded state. This report is not proposing to fix `dead-suspected` and §5.3 must not be
read as having done so. **`_record_is_live` (§2.5) sharpens it further:** those husks are `live` to
the registry-side reader for their whole lifetime, so the accumulating state is not merely
unswept — it is actively counted as alive by one of the readers this consolidation touches.
Naming it as owed work rather than folding it in: a clearing ritual for `dead-suspected` is a
different slice with a different owner, and §5.5 says why.

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
* **Not** removing the epoch freeze. §1. It gets a *surface* **and an attribution step** (§6.3
  step 6) — [REV2] because if the incident was the poll-not-push mechanism instead, a surface
  fixes nothing and the wave reads as having closed disagreement 2 anyway.
* **Not** deleting the `state != "done"` clause. [REV2] Revision 1 said "however inert it measures
  on win32"; it is **not** inert, it is load-bearing here too (§3.3), and the reason not to delete
  it is now measured rather than deferred to posix.
* **[REV2] Not** merging `_record_is_live` into Q1. §5.1 — different substrate, different
  question, and answering it from the roster would break identity resolution whenever
  `claude agents` fails. It needs a *name*, not a merge.
* **[REV2] Not** fixing the roster's own wrongness. F1 measured that `state`/`status` can both
  misreport a working session; nothing in `bin/fleet.py` can repair its upstream. What fleet can
  do is stop treating a single roster field as a process fact, which is what §6 is.

### 5.6 Is it cheaper to live with?

**No — and the honest reason is not the wall-clock.** BELIEVED: the wave-time cost of
disagreements 1 and 2 is minutes per wave, which alone would not clear the "self-repair only when
it blocks the axis" bar. **MEASURED (I read all 11), what clears the bar is that 9 of the 11 Q1
call sites gate an operation whose false-dead branch is unrecoverable** — `clean` deletes journals,
`respawn` can produce two live sessions under one name, `archive` can delete the state the wedge
gate reads, `sup-boot` can seize a live claim. The two exceptions are display-only
(`_render_boot_bundle` `:15180`, `_doctor_check_supervisor_wedge` `:18559`), and §2.2's table names
which is which.

**[REV2] Eight** of those nine are correct *today* because their callers independently re-derived
the same conservative interpretation of an out-of-band UNKNOWN. **That is not a property anybody is
enforcing; it is eight coincidences.** The ninth — `_wedged_release_gate` — re-derived the
**opposite** interpretation, deliberately, and says so in its own docstring (`:15459`): it fails
OPEN, because a speed-bump at the top of every mutating verb must not brick the CLI on a transient
roster failure.

*Revision 1 said "nine coincidences" here while §6.3 carved site 10 out — and this is the section
that motivates the work, so a successor reasoning from it and not cross-reading §6.3 would have
made that gate conservative and shipped a fleet-wide outage. That is gate finding F2, and it is
the same shape as the reasoning error §7.7 already discloses: a correction made in one place and
not swept.*

**And the tenth caller is the defect**, with `recompute_worker_native:3760` already a
half-instance — a Q1 predicate re-spelled without the clause its author called load-bearing — and
`_record_is_live` (§2.5) an eleventh, answering Q1 from the registry where §6.2's first draft had
nowhere to put it.

**[REV2] F1 raises the stakes rather than changing the conclusion.** The argument above is about
sites that are conservative *by coincidence*. F1 measured something worse: on a
`done`-with-keys entry the Q1 predicate is confidently **wrong**, and respawn's carefully
conservative UNKNOWN handling never engages, because the roster did not say "unknown" — it said
"done". *A reader that is scrupulous about ambiguity and has no defence against confident error is
the exact shape this consolidation should be designed to expose.*

The fix is ~80 inserted lines at a measured cost of **~8 re-pins at `:14656` versus ~34 at
`:3714`** (§6.5, with the population that produced those numbers). At that price it is cheaper to
fix than to keep re-deriving.

---

## 6. BUILD BRIEF FOR THE SUCCESSOR (deliverable D)

Executable on a settled `bin/fleet.py` without re-deriving anything above.

### 6.1 Files

| file | change |
|---|---|
| `bin/fleet.py` | one new function + one new `sup-status` flag; **the 4 per-sid sites re-pointed, the 7 set-consuming sites re-pointed via a set-plus-verdict return, 3 callee signatures widened**; 2 docstrings corrected. **Insertion point is not free — see §6.5.** |
| `tests/test_liveness_readers.py` | **exists on `w50/live`.** Invert every test marked `INVERT-ON-BUILD`. |
| `docs/specs/native-substrate.md` | add §0's three-facts table to the roster contract, **including that `state` and `status` were both measured wrong about a working session** (§3.1). |
| `docs/specs/terminal-surface.md` | new clause: a view never answers Q1; `sup-status --probe` is the verb that does. |

### 6.2 The predicate — **[REV2] RE-SPECIFIED. Revision 1's signature was unimplementable.**

Revision 1 proposed a per-sid scalar, `roster_body_state(roster_ok, entries, sid) -> str`. The
gate (F6) measured that **only 4 of the 11 sites have a per-sid shape at all** — `:8230`, `:8249`,
`:8255`, `:9412`, all inside respawn. The other **7 consume the SET**: `_any_live` intersects a sid
union; `cmd_clean` passes the set (or `None`) into `_clean_spares_released_body_evidence`;
`_archive_eligible`, `_wedged_release_gate`, `cmd_sup_boot` and doctor pass it into
`_releaser_live_sids` / `supervisor_claim_decision`; `_render_boot_bundle` takes `len()`. For those
seven, a per-sid scalar leaves UNKNOWN out-of-band — **the precise defect the ruling exists to
remove**, and site 10, the trap, is one of them.

**The corrected shape returns the set AND the verdict together:**

```python
# INSERT IMMEDIATELY BELOW `_roster_live_sids` (currently :14656) -- NOT near
# `recompute_worker_native`. See the re-pin measurement in §6.5.

ROSTER_LIVE, ROSTER_GONE, ROSTER_UNKNOWN = "live", "gone", "unknown"

class RosterLiveness(NamedTuple):
    """Q1's answer: WHICH sids are backed by a live host process, and WHETHER
    fleet actually knows. `known=False` means the roster could not be read --
    `sids` is then empty and MUST NOT be read as "nothing is alive".

    Held as one value because every caller today reconstructs it from two --
    `_roster_live_sids(entries)` plus an out-of-band `roster_ok` -- and the
    eleven reconstructions agree by coincidence rather than by construction
    (w50 report 2.2). Eight are conservative, one (`_wedged_release_gate`)
    deliberately is not, and nothing enforces either.

    NEVER PERSISTED, and that is what makes a third value safe here where
    `dead-suspected` was not: this is computed per call and has no storage, so
    it cannot accumulate and needs no clearing ritual. Its ritual is the next
    roster fetch.

    THIS ANSWERS NOTHING ABOUT THE TURN, and on win32 it cannot: `state` and
    `status` were both measured reporting `done`/`idle` for a session that was
    executing a turn (w50 3.1). Key presence is the only roster field that
    tracked the process. `recompute_worker_native` owns the turn question.

    THIS IS ALSO NOT `_record_is_live` (:2993), which asks whether FLEET has
    retired a record. Different substrate, different question, deliberately
    not merged (w50 5.1)."""
    known: bool
    sids: frozenset

    def state_of(self, sid) -> str:
        if not self.known:
            return ROSTER_UNKNOWN
        return ROSTER_LIVE if sid in self.sids else ROSTER_GONE


def roster_liveness(roster_ok: bool, entries) -> RosterLiveness:
    return RosterLiveness(bool(roster_ok),
                          frozenset(_roster_live_sids(entries) if roster_ok else ()))
```

`state_of` serves the 4 per-sid sites; the value itself serves the 7 set-consuming ones. **The
tri-state now reaches every site in-band, which the scalar could not do.**

**`_roster_live_sids` stays**, unchanged, as the membership rule — `roster_liveness` wraps it.
Re-keying `_releaser_live_sids`'s fork-steer union is explicitly **not** in this slice; its
docstring's boundary argument is load-bearing.

**Budget the three callee signature changes revision 1 omitted** (gate F6):
`_clean_spares_released_body_evidence(record, released_by, live_sids)`,
`_releaser_live_sids(claim, live_sids, registry=None)` and
`supervisor_claim_decision(claim, live_sids, ...)` each take a bare set today and must take a
`RosterLiveness`. **`_archive_eligible` is the sharp one**: its signature is
`(name, record, roster_entries, now, ttl_hours=)` — it takes no `roster_ok` at all and receives
`[]` on failure, so **the site itself cannot distinguish UNKNOWN from GONE**; the refusal lives in
its caller at `:10501`. Giving site 7 the tri-state is a signature change, not a re-point.

### 6.3 Call-site changes

1. **`recompute_worker_native:3760`** — replace the inline `live = entry is not None and (...)`
   with `roster_liveness(...).state_of(sid) == ROSTER_LIVE`. This closes the latent third
   spelling. *Then re-read §5.1: `status` must stay liberal, so on `ROSTER_UNKNOWN` it takes the
   `has_fresh_outcome` path exactly as it does today for a roster-gone sid. Do not make it
   conservative.*
2. **The 9 non-display Q1 sites** — thread the `RosterLiveness` value through instead of the bare
   set plus an out-of-band flag. **Each site keeps ITS OWN mapping — do not give them a shared
   one.** Per §2.2's policy table:

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
4. **`_roster_live_sids`'s closing parenthetical** — replace with §3.5's [REV2] wording. Revision
   1's proposed replacement would have shipped a **false** sentence ("currently inert here") into
   `bin/fleet.py`; do not use it.
5. **`_roster_entry_has_life_signal`** — add one sentence: *"This is NOT Q1. It answers 'did this
   session ever attach', and on **131 of the 139** entries measured 2026-08-09 it returns True
   where `roster_liveness` returns GONE. Both are correct."*
6. **[REV2] `_record_is_live` (`:2993`)** — rename it or document it, but do not leave it called
   `live`. It answers Q1r (has fleet retired this record) from the registry, and it entered this
   census only by resemblance. Suggested docstring line: *"NOT roster liveness. This never
   consults a process; a `dead-suspected` husk is `live` here for as long as it exists."*
7. **[REV2] Attribute disagreement 2 before claiming it is fixed** — one `log`/stderr line when
   `epoch_frozen` short-circuits a wait or a status recompute, naming the freeze. This is the
   cheapest thing that turns the next occurrence into evidence. **Without it the surface may be
   fixing a mechanism that never fired** (§1's caveat): if the incident was poll-not-push, a
   freeze surface changes nothing and the wave will read as having closed disagreement 2.

### 6.4 Tests that must go RED first, and the mutants that prove them

| # | test (RED first) | mutant that must make it RED |
|---|---|---|
| M1 | `roster_liveness(...).state_of(sid)` returns `ROSTER_UNKNOWN` on `roster_ok=False` | `return ROSTER_GONE` on the failure arm |
| M2 | **each Q1 site keeps the UNKNOWN mapping §6.3 assigns it — per site, not in aggregate** | two mutants, both required: (a) flip **one** conservative site's UNKNOWN branch to proceed; (b) flip `_wedged_release_gate`'s UNKNOWN branch to *arm*. The test must name *which* site each time — an aggregate assertion passes on the other 8, and (b) is the one a "unify the policy" refactor introduces |
| M3 | `recompute_worker_native` still reaches `has_fresh_outcome` on UNKNOWN | make it conservative → the test must go RED, proving Q2 stayed liberal |
| M4 | the tri-state is never persisted | write it into `new_worker_record`'s schema; a grep-based test is **not** sufficient — assert `state/fleet.json` bytes carry no such key after a full status/wait/clean cycle |
| M5 | **[REV2]** the `done`-clause deletion is caught | delete `and e.get("state") != "done"`. Revision 1 said this mutant "SURVIVES on win32 today" and told the successor to reach for a synthetic posix entry. **Both halves were wrong**: the gate measured it already RED against the shipped file (`1 failed, 19 passed`), and §3.3 measures the clause is load-bearing on win32. Keep the mutant; drop the posix framing. |
| M6 | `sup-status` without `--probe` performs no subprocess | make the non-probe path fetch the roster; assert via a `run=` seam that records calls, not by timing |
| M7 | every test marked `INVERT-ON-BUILD` fails if the readers are *not* unified | revert one call site |
| **M8** | **[REV2] no test in the file passes by asserting SOURCE TEXT** | for each test, plant a mutant that breaks the named property while leaving every string in `bin/fleet.py` intact. This is gate F3 turned into a standing obligation: three of the original twenty failed it, and the driver in §6.6 is the harness. |
| **M9** | **[REV2] the Q1 call-site census pins the POPULATION** | relocate one Q1 read out of `_wedged_release_gate` and add a compensating call elsewhere so the total is unchanged (gate F4's two-part M-D). A count assertion cannot see this; a scope multiset can. |

**Also carry forward, unchanged:** `test_a_released_claim_has_no_beat_and_that_is_not_staleness`.
A released claim's `heartbeat_age_seconds is None` means *correct stand-down*, never *stale*; any
canonical answer must keep saying so. That lesson is already paid for.

### 6.5 [REV2] Self-citation cost — with the population, because without it the numbers are not reproducible

Wave 47 measured 37 inserted lines → 32 re-pinned citations. **That ratio is not a constant; it is
entirely a function of WHERE the insert lands,** because only citations *below* it move.

Revision 1 quoted **36 / 26 / 7** as MEASURED constants. The gate could not reproduce them under
any population it constructed (F8) — it got 42/34/8, 33/27/6, 25/21/8 and 5/5/0 depending on how a
"self-citation" is defined. **The gate is right that a number a successor cannot re-derive is not
a budget.** My 36 came from a specific definition I did not state:

> a `:NNNN` token in `bin/fleet.py` resolving in-range, **excluding** slice literals (`[:200]` —
> excluding `[` from the lookbehind, which alone moved the count from 53 to 36) and **excluding**
> lines mentioning another document (`three-tier-command.md :432-437`, `SPEC`, `CN:`, `SPAWN:`,
> `multi-fleet`), since `tests/test_self_citations.py` resolves line numbers against `fleet.py`
> and nothing else.

| insertion point | re-pinned (my population, n=36) | re-pinned (gate's occurrence population, n=42) |
|---|---|---|
| next to `recompute_worker_native` (`:3714`) | 26 | 34 |
| next to `_roster_live_sids` (`:14656`) | 7 | 8 |
| next to `cmd_sup_status` (`:16779`) | 2 | 2 |

**What is robust across every population, and is the only thing a successor should budget
against: the RANKING and the ~4× ratio.** `:14656` is the correct insertion point; `:3714` costs
roughly four times as much for no design benefit. **Re-derive the absolute number against
`tests/test_self_citations.py`'s own scanner before quoting it** — do not inherit 36, or 42.

**Estimate: ~80 inserted lines (≈50 predicate + docstring, ≈20 `--probe`, ≈15 across call sites),
landing at `:14656` and `:16779`, for single-digit re-pins.** **Insert low in the file and
re-point upward.** Re-pin FORWARD in the same commit and warn the supervisor, per the day-5 lesson.

### 6.6 [REV2] The mutation driver is a deliverable, not a one-off

`tests/test_liveness_readers.py` is now graded by a driver that: exports `git archive HEAD` to a
scratch tree so the worktree's `bin/fleet.py` is never written; asserts `occurrences == 1` for
every patch anchor **before** running anything; requires a green floor first; and proves each
restore by sha256 against the floor digest. Five mutants (M-A/M-B2/M-C/M-D/M-E), all KILLED. **A
successor adding a test to this file should add its mutant to that ledger in the same commit** —
the three tests that failed gate F3 were all added without one.

---

## 7. WHERE THIS BRIEF WAS WRONG

| # | the brief's claim | verdict |
|---|---|---|
| 1 | "These are three instances of one class" | **PARTLY WRONG.** #1 and #3 are one class. **#2 is a different class** — a correct, deliberate safety freeze whose only defect is silence, and unifying it would produce a wrong fix. **[REV2] Stated with LOW confidence about the incident**: the classification is sound, the attribution is not. I reproduced a mechanism that produces the symptom and could not tie it to the incident; poll-not-push fits equally well. §1's caveat governs, and §6.3 step 7 adds an attribution step so the next occurrence is evidence. |
| 2 | "The `_roster_live_sids` Windows parenthetical is the cause of disagreements 1 and 2" | **[REV2] THE PREMISE REPRODUCES; THE CAUSAL INFERENCE FROM IT IS STILL WRONG.** Revision 1 said the premise did not reproduce, and that was my error, not the brief's — see §7.8. MEASURED now: three concurrent `done`-with-keys entries, one of them mid-turn (§3.1), so the parenthetical is false in the direction the brief claimed *and* in the reverse. But the entry that actually splits `respawn` from `status` is `blocked`, not `done` (§3.4), so the parenthetical still does not explain disagreement 1. **Two defects in the same six lines: a false comment, and a reader answering a process question with a run-fact.** |
| 3 | "`heartbeat_at` refreshes only on `sup-*` verbs" | **RIGHT.** MEASURED: 8 write sites, all in `cmd_sup_*` functions bound to `sup-*` verbs; no hook writes it. §2.4. |
| 4 | "10 call sites, counted by grep" | **WRONG, and in the direction the brief did not guess.** MEASURED: **11**. Grep's 14 = 11 calls + 1 def + 2 docstring mentions. The brief expected the grep to over-count; it under-counted. §2.2. |
| 5 | "A read-only lane can settle this" | **RIGHT.** Every finding here is a pure-function or AST measurement plus one read-only vendor roster fetch. No production change was needed to reach the ruling, and no live fleet verb was run. |

**A sixth, which the brief did not list.** It named five readers to start from and asked me to go
beyond them. The one that most sharpens the finding is `_roster_entry_has_life_signal` — a shipped
predicate that returns **the exact opposite** of `_roster_live_sids` on **131 of 139** entries
(§2.3). **[REV2] And the population was still not closed: the gate found `_record_is_live` (§2.5),
which I had missed.** A census that started and stopped at the named five would have missed both.

### 7.7 My own defects, found by me — three

1. My first heartbeat census reported **5** writers. There are **8**: `ast.Dict` keys are not
   `ast.Subscript` stores. Caught by a reconciling control, not by review; the control is now in
   the test file, and the gate rated that test the strongest in it.
2. My first timestamp fixtures were unparseable by `_parse_iso`, which would have made the
   recompute tests green **through the dispatch-grace branch instead of the roster branch they
   name** (§4.1). Caught by a failing assertion, then guarded by `_grace_is_shut`.
3. **§2.2's first draft generalised from two sites**: *"every one of these callers already refuses
   on an unfetchable roster or spares on an unknown one"*. `_wedged_release_gate` (`:15459`)
   **fails OPEN**, deliberately. Would have shipped a build brief telling the successor to make
   that gate conservative — an outage. §6.3 names it as the trap; §6.4 M2(b) is its mutant.

### 7.8 [REV2] My own defects, found by the GATE — and the first is the biggest error in the report

4. **THE HEADLINE WAS FALSE.** *"The predecessor's measurement does not reproduce"* — it
   reproduces. §3.1. And the error is worth more than the correction: **my detector control was
   correct and passed, and I still generalised a single snapshot taken by a busy session into a
   property of the platform.** Wave 38's lesson is *run the control*; this lane's is that **a
   control proves the detector can see the shape, not that the window contained it** (§3.6). Five
   further sections descended from that one sentence, including a proposed docstring that would
   have shipped a false statement into `bin/fleet.py`.
5. **Three tests asserted SOURCE TEXT, and four mutants survived the whole file** — a `--force`
   bypass of respawn's refusal, `clean` dooming instead of sparing, the supervisor gate's disarm
   deleted, and a Q1 call site relocated out of the trap behind a count-preserving decoy. §4.4.
   *The file written to answer wave 35 contained wave 35's defect.*
6. **The reader population was asserted closed by omission** (§2.5), the **census pinned a count
   rather than a population** (§4.4), **"60 of 137" was one population counted twice** and
   understated my own finding by more than half (§2.3), **§6.2's predicate signature was
   unimplementable at 5 of 9 sites** (§6.2), the **re-pin numbers were unreproducible without the
   population definition** (§6.5), the **`INVERT-ON-BUILD` count was stated three ways** (§4), and
   **`LIVE_SHAPE` was called "verbatim" when it is a splice of two entries** (§4).

**The pattern across 1–6, and I would rather name it than have a third gate find it:** every one
is *a claim that outran its evidence by one step*. The apparatus defects (1, 2) were caught by
controls. The reasoning defects (3, 4, 6) were caught by re-reading the population — twice by me,
more often by the gate. **The class is not carelessness; it is that a measurement licenses a
narrower statement than the one it feels like it licenses**, and the only defence that has
actually worked in this lane is going back to enumerate rather than trusting my own summary.

---

## 8. SAFETY — exactly what I ran

**Live fleet verbs run: NONE.** Not `status`, not `peek`, not `result`, not `doctor` — the brief
permitted those four and I did not need any of them, in either revision. Every reproduction is a
pure-function or driven-CLI test against a sandboxed `FLEET_HOME`.

**The live reads:** `claude agents --json --all` — once in revision 1, and **[REV2] 29 times from
a detached sampler** (`Start-Process`, PID 43584, 20s interval, self-terminating), captured to
`$CLAUDE_JOB_DIR/tmp/samples.jsonl` outside the repo. That is the vendor CLI's own read-only
listing: it takes no `fleet.lock`, reads no fleet home, and is the same command
`_fetch_agents_roster` shells out to. Plus `tasklist /FO CSV /NH` per pid.

* No `fleet init`, no `FLEET_HOME` set or exported, no `--fleet-home` passed (no fleet verb ran at
  all against the live home).
* `~/.claude/settings.json` and `~/.claude/fleet-homes.list` never opened for write.
* **[REV2] All mutation ran on a `git archive HEAD` scratch export** at `$CLAUDE_JOB_DIR/tmp/mut`.
  `bin/fleet.py` in this worktree was never written — the driver re-checks
  `git diff --quiet HEAD -- bin/fleet.py` after every run and reports it.
* Test runs are sandboxed by `tests/conftest.py`'s autouse fixtures; the session-scoped
  code-plane hash guard passed on both interpreters.
* Nothing that matters lives under `state/` — this report is committed at `docs/lanes/w50-live.md`
  and the tests at `tests/test_liveness_readers.py`. `state/journals/w50-live.md` holds working
  state only.
* **[REV2] `docs/lanes/w50-glive.md` was not edited.** Read via `git show w50/glive:...` into a
  scratch file; the gate's artifact is untouched evidence.
* Branch `w50/live` only. No push, no merge, no other ref moved. `bin/fleet.py` byte-identical.

---

## 9. [REV2] WHAT I AM CONTESTING

The gate asked for this explicitly, and the honest answer is **one finding, partially — and it is
a scoping disagreement, not a factual one.** Everything else I reproduced or accepted on the
gate's own receipts, including every finding that cost me a section.

### F11 — "the floor-delta ordering claim is self-attested" — ACCEPTED AS TO FACT, CONTESTED AS TO REMEDY

**The gate is factually right.** Revision 1 tagged *"predicted in the journal before running, then
measured"* as MEASURED. `state/journals/w50-live.md` is gitignored, mutable, and carries one
mtime; nothing outside my own session preserves the ordering. It was a **BELIEVED**, and it is
re-tagged.

**What I contest is the implied remedy — "the prediction has to land somewhere append-only or
committed" — as a general rule.** For this lane it is cheap and I have done it: the floor
prediction for REV2 is committed as its own commit *before* the run, so the ordering is in
`git log` where anyone can check it. But as a standing rule it does not survive its own logic.
A committed prediction is only evidence if the commit *timestamp* is trusted, and a lane can
author both commits in either order before pushing either. **Pre-registration inside a repo the
predictor controls is a convention, not a proof**, and treating it as MEASURED would reintroduce
exactly the error F11 is correcting, one level up.

**So: the prediction is committed first because it is nearly free and it raises the cost of
self-deception. It is still labelled BELIEVED.** A genuine receipt would need an attestation the
lane cannot author — CI, or the fleet's own append-only `events.jsonl` — and *that* is worth
proposing as method, which I am doing here rather than quietly complying.

### Not contested, for the record

F1 (I re-measured and found it worse than the gate did), F2, F3, F4, F5, F6, F7, F8, F9, F10, and
the scope-narrowing confidence call. **F3 and F4 in particular were findings I would not have
found**: the mutants that survived my own file were survivable precisely because I wrote the tests
believing they pinned behaviour.
