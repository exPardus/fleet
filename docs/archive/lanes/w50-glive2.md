# `w50-glive2` — second gate on `w50/live`. **GATING.**

| | |
|---|---|
| Branch under gate | `w50/live` @ `74e3944` (commits `29cb116`, `f9fa57e`, `74e3944`) |
| This branch | `w50/glive2` @ `74e3944` (branched from `w50/live`). This file is the whole diff. |
| Scope | **NARROW.** Q1–Q4 on the *replacement* headline claim only, plus F11's contest and two mutant spot-checks. The first gate's broad review (`w50/glive`, `ffaad73`) is **not** re-run. |
| Verdict | **GATING — 2 BLOCKING / 5 MAJOR / 5 MINOR / 6 CLEARED** |
| Live verbs run | **NONE.** `claude agents --json --all` (69 detached samples + 1 inline), `tasklist`, `Get-CimInstance Win32_Process`, and one read-only `open()` of `state/fleet.json`. No fleet verb, no lock, no write to the live home. §S. |
| `bin/fleet.py` | never written. All mutation on a `git archive HEAD` scratch export; sha256-verified restore after every run. |

Every line is **MEASURED** (I ran it in this gate and read the output) or **BELIEVED** (reasoning
or code-reading I did not execute).

---

## 0. THE VERDICT IN ONE PARAGRAPH

The measurement reproduces and is real (**Q1**). The blindness is real by construction (**Q2**).
But the two words the finding is built on do not survive: the four instances are **not** lingering
husks, they are **four idle workers in their ordinary resident state** (**Q3**), and the
correction did **not** survive its own correction — the retracted mid-turn claim is still live at
four sites, one of which instructs the successor to write it into `docs/specs/native-substrate.md`
(**Q4**). And the replacement claim is itself an inference one step past its evidence: **MEASURED
by mutant, fixing the exact defect the headline names leaves all 32 tests green**, including the
`INVERT-ON-BUILD` test that exists to pin it — because the branch's own §6.2 build brief
deliberately leaves `_roster_live_sids` unchanged, so the headline defect survives the branch's
own build untouched while §5.2 claims §6.2 is the answer to it.

**The brief guessed right that Q4 is the sharp one.** It also guessed that Q2 might simply be
wrong on the code and downgrade everything. Q2 is *right* on the code and it changes little,
because Q3 is where the finding actually loses its load.

---

## Q1 — IS THE MEASUREMENT REAL? **YES.** MEASURED, with a stronger identity check than the lane's.

### Q1.1 The shape reproduces, independently

A detached sampler (`Start-Process`, launcher pid 8288 / python pid 44712), polling
`claude agents --json --all` every 10 s, **69 samples, 06:48:46Z → 07:01:33Z**, controls run and
recorded *before* the first sample:

```
CONTROL  detector_positive : 2 (expect 2)  PASS   <- synthetic roster, two done-with-keys entries
CONTROL  detector_negative : 0 (expect 0)  PASS   <- same roster with those entries removed
CONTROL  grouping_positive : ['ctlworker'] PASS   <- a worker holding two keyed entries IS grouped
CONTROL  grouping_negative : []            PASS   <- one keyed entry is NOT
CONTROL  pid_self_alive    : True          PASS   <- tasklist CSV ROWS, not exit code
CONTROL  pid_bogus_alive   : False (999999) PASS
CONTROL  identify_self     : {"name":"python.exe", ...}  PASS
CONTROL  identify_bogus    : {}            PASS
PASS = true

done+keys per sample: min 3, max 4     roster fetch failures: none
```

Four concurrent `state:"done"` entries carrying `pid` and `status:"idle"`, stable across the run.
**The lane's Q1 conclusion holds.**

### Q1.2 The lane established pid EXISTENCE. I established pid IDENTITY, and it holds.

The lane's check is a `tasklist` row. That excludes nothing about **pid reuse**. Closing it:

```
pid    image        entry.startedAt   Win32_Process.CreationDate   delta      state/status  worker
20704  claude.exe   17:31:41Z         17:31:39Z                    +2.7s      None/busy     (interactive)
37220  claude.exe   18:06:57Z         18:06:55Z                    +2.1s      None/idle     (oracle)
33120  claude.exe   04:50:27Z         04:50:26Z                    +1.5s      working/busy  (supervisor)
41176  claude.exe   05:00:06Z         05:00:05Z                    +2.0s      done/idle     w50-launchfix
26660  claude.exe   05:00:20Z         05:00:19Z                    +1.4s      working/idle  w50-d
41464  claude.exe   05:00:28Z         05:00:27Z                    +1.5s      done/idle     w50-fs2
38740  claude.exe   05:31:15Z         05:31:14Z                    +2.0s      done/idle     w50-glive
15364  claude.exe   05:57:52Z         05:57:50Z                    +2.2s      working/busy  w50-gfs
20960  claude.exe   06:03:40Z         06:03:39Z                    +1.5s      done/idle     w50-live
11928  claude.exe   06:20:01Z         06:20:00Z                    +1.7s      working/busy  w50-gd
45824  claude.exe   06:21:44Z         06:21:42Z                    +2.5s      working/busy  w50-glaunch
49416  claude.exe   06:44:24Z         06:44:22Z                    +2.2s      working/busy  w50-glive2 (me)
```

MEASURED, 12/12: the process is a `claude.exe` created **1.4–2.7 s before** the session's own
`startedAt`, in one direction, with no outlier. A pid-reuse coincidence would have to reproduce
that binding twelve times. **Identity established; the entries name the processes they claim.**

**MINOR m1 — the branch's receipt does not contain this step.** Its evidence is
`pid 4436 alive=True`. I cannot retro-verify pid 4436: MEASURED, that process is **gone**
(`Get-CimInstance` returns nothing for 4436, and entry `b9b2124d` now carries neither `pid` nor
`status`). The sharpest single instance in the report is now permanently unverifiable, and it was
never identity-checked while it could be.

### Q1.3 **MAJOR M5 — the lane's stated reason for its own error is wrong, and this brief inherited it.**

§3.0: *"a session executing a measurement is `busy`, so its own entry cannot exhibit a turn-end
shape at the moment it looks"* → therefore *"The replacement observes **from outside**"*, and §3.5
routes *"from outside every session observed"* into a proposed `bin/fleet.py` docstring. The brief
restates it: *"the whole reason the earlier number was wrong is that a measuring session is always
`busy` and structurally cannot contain the shape."*

**MEASURED, and it is false.** The very first thing this gate ran was **one inline snapshot from
inside this busy fleet worker**, before any sampler existed:

```
--- done+keys ---  (single snapshot, taken from inside session 602ac003, state working/busy)
  DONE+KEYS 5bd99e65 41176 idle fleet|w50-launchfix|...
  DONE+KEYS 93f5c952 41464 idle fleet|w50-fs2|...
  DONE+KEYS 2d3724ff 38740 idle fleet|w50-glive|...
  DONE+KEYS 9d9509b2 20960 idle fleet|w50-live|...
--- state histogram --- {'done': 75, 'failed': 2, 'stopped': 26, 'blocked': 33, None: 2, 'working': 6}
```

n=4, from inside, in one instant. The observer's own entry is **1 of 144**; the shape lives in the
other 143, which the observer's busy-ness cannot touch. **Detachment was never the load-bearing
property — DURATION was**, and §3.6's own lesson (*"a control proves the detector can see the
shape; it does not prove the window contained it"*) states that correctly. §3.0's diagnosis and
§3.6's lesson therefore disagree, and §3.0 is the wrong one.

Why it matters rather than being pedantry: a successor who reads §3.0 learns that an
inside-session measurement *structurally cannot* see this class of shape. That is a false
dismissal rule, and it would license discarding a valid measurement. **BELIEVED**, on the
measured components above.

---

## Q2 — IS THE CONSEQUENCE CLAIM RIGHT? **The blindness is. The sentence around it is not.**

### Q2.1 Blindness — CONFIRMED by construction. MEASURED.

`_roster_live_sids` (`:14656`) excludes `e.get("state") != "done"`; `_any_live` (`:9447-9451`)
returns `bool(gate_sids & _roster_live_sids(entries))`. A `done`-with-keys sid in `gate_sids` is
therefore invisible to the intersection **for every possible roster**, not merely for the one
observed. No argument needed.

### Q2.2 Falsification — I looked for a second guard. **There is none, and one of the two the lane could have claimed cuts the other way.**

* **No OS pid probe exists anywhere in `bin/fleet.py`.** MEASURED:
  `grep -n "tasklist\|os\.kill\|psutil\|OpenProcess\|pid_alive\|_pid_is\|proc_exists" bin/fleet.py`
  → **0 hits**. Nothing in the tree ever converts a roster `pid` into an OS liveness question.
* **The named downstream guard inherits the same blindness.** `_any_live`'s own comment says
  *"The boot-side rule 1 would refuse the successor anyway"* — but `cmd_sup_boot:15230` computes
  `live_sids = _roster_live_sids(entries)`, the identical predicate. It does not catch it.
  `_releaser_live_sids` (`:14818`) is likewise built on it.
* **No `--force` bypass** on the `_any_live` arm: it raises `SupervisorLifecycleRefusal`
  unconditionally.

So the lane is right that nothing catches it. **But there is an UPSTREAM mitigation it does not
mention, and it is the reason the invariant is not actually breached:** before `_any_live` runs,
`_cmd_respawn_supervisor:9430-9434` **unconditionally `claude stop`s every retired sid** (capped
at `_RETIRED_SID_SWEEP_CAP`, 5 s each), and `_cmd_kill_native:8628-8646` does the same. Those
sweeps are not incidental — they exist for this exact shape, and the file says so:

> `:8509-8511` — *"`claude stop` the current sid (G10: never raw-kill) plus every retired sid
> best-effort (**a steered-away fork per Steering contract may still be live** even though this
> record's own current sid has moved on)"*
>
> `:9420-9424` — *"A landed steer against an idle holder fork-steers, so `session_id` is the live
> fork and the pre-steer sid sits in `retired_sids` — and **the Steering contract leaves that
> parent's roster entry untouched, so it may still be live too.** Primary gets the full timeout;
> the retired parents are swept best-effort."*

**MAJOR M3 — "two live sessions under one name from a retired fork" is not a discovery; it is a
documented property of the Steering contract, with compensations already built at two sites.**
The lane presents it as newly measured and as an unguarded hole. What is genuinely new is only the
win32 *frequency*, and Q3 shows even that is mis-attributed.

### Q2.3 **MAJOR M1 — the named instance cannot reach the named code path.** MEASURED.

`cmd_respawn` routes to `_cmd_respawn_supervisor` only via `_supervisor_lifecycle_target`
(`:8448`) or `_is_supervisor_shaped(args.name)` (`:8483`); every other record falls to
`_cmd_respawn_native` (`:8500`). `w50-live` is an ordinary worker. **`_any_live` never runs on
it.** The union blindness is independently true *for supervisor records*; the sentence in §0 that
welds this worker observation to `_cmd_respawn_supervisor` is an inference, and it is the load
path of the headline.

### Q2.4 And the worker path's real behaviour is **worse than the report states, in a way the report gets backwards.** MEASURED.

`_cmd_respawn_native` gates on the **current sid only** (`:8230`), and the entire
stop-and-reverify block is inside `if old_live:`. When Q1 says not-live, **no stop is attempted at
all** — no `claude stop`, no tombstone. Driven, with a control proving the recorder is wired:

```
tests/test_glive2_probe.py::test_respawn_attempts_NO_STOP_AT_ALL_on_the_lingering_shape   PASSED
tests/test_glive2_probe.py::test_CONTROL_the_same_drive_DOES_stop_when_the_entry_reads_working PASSED
tests/test_glive2_probe.py::test_the_headline_pin_never_executes_the_function_it_names    PASSED
3 passed in 11.38s
```
*(scratch tree only; recorded here, not committed to the branch — §S.)*

The first asserts `calls == []` for both stop functions **and** `write_tombstone_outcome`; the
second shows the identical drive records `["stop", "tombstone"]` once the entry reads `working`.
The branch's own test docstring for this case says respawn *"proceeds to **stop** a session whose
OS process is alive and mid-turn"* (`tests/test_liveness_readers.py:538`). **Both halves are
wrong** — see M4.

---

## Q3 — IS "ORDINARY RE-DISPATCH" THE RIGHT ATTRIBUTION? **NO. This is where the finding loses its load.**

### Q3.1 **MAJOR M2 — all four instances are IDLE WORKERS, not lingering husks.** MEASURED.

One read-only `open()` of `C:\proga\claude-fleet\state\fleet.json` (no lock, no verb, no write),
classifying each of the four `done`-with-live-pid sids against the registry:

```
workers in registry: 156
  w50-fs2          status=idle     cur=93f5c952 retired=[]
  w50-glive        status=idle     cur=2d3724ff retired=[]
  w50-launchfix    status=idle     cur=5bd99e65 retired=[]
  w50-live         status=idle     cur=9d9509b2 retired=['b9b2124d']
  w50-glive2       status=working  cur=602ac003 retired=[]

5bd99e65 : [('w50-launchfix','CURRENT')]     93f5c952 : [('w50-fs2','CURRENT')]
2d3724ff : [('w50-glive','CURRENT')]         9d9509b2 : [('w50-live','CURRENT')]
b9b2124d : [('w50-live','RETIRED')]
```

**4 of 4 are the workers' CURRENT `session_id`, and all four workers are `idle`.** So
`state:"done"` + `status:"idle"` + a live pid is **the ordinary resident state of an idle fleet
worker between turns** — not a finished session whose host process failed to exit. Only
`b9b2124d` was ever a retired sid, and MEASURED it is now dead with its keys gone.

This inverts the finding's polarity. `_roster_live_sids`'s own docstring records the bug the
`done` clause was **added to fix**:

> *"a finished bg session's host process can LINGER after its turn ends … The key-presence
> heuristic alone therefore misreads it as live (**observed blocking `fleet respawn` on an idle
> worker**). The documented terminal-state rule must dominate key presence."*

So the clause returning not-live for these four is **the clause performing its stated purpose on
its stated primary case**. §0 leads with *"`_roster_live_sids` returns not-live for a live process
… every caller gets a false DEAD"*; on 4 of the 4 instances offered, the caller's question is *"is
a turn running?"* and the answer **not-live is correct**. §5.2 does price the trade-off honestly;
§0 does not, and §0 is what a successor reads.

### Q3.2 **MINOR m4 — it is a window, and the window has a measured length.** MEASURED.

The sampler caught one closing end-to-end:

```
CHANGE i=42 06:56:44Z  +[]  -[('93f5c952','done','idle',41464)]
   (pid 41464 was never observed alive-but-keyless: the process exit and the
    key loss fall inside the same <=10s interval)
```

`93f5c952` held `done`+`idle`+live pid from `startedAt` 05:00:28Z to 06:56:44Z — **1 h 56 m** —
then process and keys went together. Independently: `b9b2124d`/pid 4436 was alive at the lane's
own 06:28:10Z sample and **dead with keys gone by 06:47Z**. So the entry *does* get reaped, on a
~2 h timescale, and the roster's steady state after reaping is exactly what the Windows
parenthetical describes. **The parenthetical is not simply "FALSE ON WIN32 IN BOTH DIRECTIONS" as
§3.5's proposed docstring would ship — it is false during a bounded residency window and true
after it.** A successor told "do not restore it" without being told about the window has been
handed a smaller truth than the one measured.

Correspondingly: `multi_keyed` — a worker holding two keyed entries at once — was **empty in all
69 samples**. The two-live-entries state is real, rare, and transient; the report renders it as
the branch's headline.

### Q3.3 **MINOR m3 — three mechanisms, not "ordinary re-dispatch".** MEASURED (code) / BELIEVED (completeness).

| mechanism | leaves the parent live? | receipt |
|---|---|---|
| `cmd_send` fork-steer | yes | `:7691` mints a new sid; `:9420-9424` states the parent entry is untouched |
| `resume-limited` | yes | `_resume_one_limited_native:7740` — *"`claude --bg --resume <old_sid>` MINTS A NEW SID (the original session's own roster entry, sid, and event count are left untouched, Steering contract)"* |
| `respawn` on a not-live-per-Q1 entry | yes, **and with no stop attempted** | Q2.4, driven |

"Ordinary re-dispatch" reads as *any* dispatch and is the word that converts a one-off into a
systemic property. The accurate statement is narrower and more useful: **the three sid-minting
fork-steer paths leave the parent resident, by contract, and two of them already sweep it.** I did
not attempt to close this enumeration; a name-sweep argument would be the same closure error §2.5
warns about.

---

## Q4 — DID THE CORRECTION SURVIVE ITS OWN CORRECTION? **NO, on both readings.**

### Q4.1 **BLOCKING B1 — §6.1 still instructs the successor to write the retracted claim into a spec file.** MEASURED.

`docs/lanes/w50-live.md:899`:

> \| `docs/specs/native-substrate.md` \| add §0's three-facts table to the roster contract,
> **including that `state` and `status` were both measured wrong about a working session**
> (§3.1). \|

§3.1 [REV2b] is the section that **retracts** this: *"my current sid is `9d9509b2` (pid 20960),
reading `working`/`busy` **correctly** … **The roster was right and I had mis-identified
myself.**"* And §0's three-facts table does not say it either — its `status` row reads *"MEASURED
and **accurate wherever I could check it**"*. So the instruction misdescribes both the section it
cites and the table it points at, and its destination is `docs/specs/**` — doctrine.

The brief's own statement of the near-miss was: *"It would have shipped a false claim about vendor
behaviour into `docs/specs/native-substrate.md`."* **It still would.** This is exactly finding F2's
shape — a correction recorded in one section and contradicted in another — filed *against this
very branch*, disclosed at §7.7(3) and §7.8(6), and reproduced in the commit that discharges it.

### Q4.2 **MAJOR M4 — three further residue sites, two of them inside the test file.** MEASURED.

| site | text | why it is false |
|---|---|---|
| `docs/lanes/w50-live.md:841-842` (§5.5) | *"F1 measured that `state`/`status` can both **misreport a working session**"* | Directly contradicted 34 lines later at `:875-877`: *"on a `done`-with-keys entry the roster is **accurate**"*. Both are in §5. |
| `tests/test_liveness_readers.py:538` | *"proceeds **to stop** a session whose OS process is alive **and mid-turn**"* | Wrong twice: the fixture is `state:"done"`/`status:"idle"` (not mid-turn — that IS the retraction), and MEASURED (Q2.4) **no stop is attempted at all**. The test monkeypatches both stop functions, so it cannot observe its own docstring's claim. |
| `tests/test_liveness_readers.py:561` | *"two string fields **the roster got wrong**"* | The roster got them right. §0: *"the roster reports each accurately about itself."* |

The class docstring at `:472-504` carries the REV2b correction explicitly. **Two of its four test
docstrings still carry the retracted version.** The correction is recorded at the top of the class
and contradicted inside it — and the test file is the durable artifact the build inverts, so this
residue outlives the report.

### Q4.3 **BLOCKING B2 — the replacement claim is the same inference shape, and it is measurably unpinned.**

The brief's harder question was whether the replacement is *also* an inference confirming a
correction just handed over. It is, and I can drive it rather than assert it.

**The claim's only pin does not execute the function the claim names.**
`test_the_union_gate_cannot_see_a_live_retired_body` (`:518-534`) re-implements the intersection
inline — `union & fleet._roster_live_sids([...])` — and never enters `_cmd_respawn_supervisor`
(driven: `test_the_headline_pin_never_executes_the_function_it_names`, PASSED). That is the same
defect class as gate finding **F3**, which this commit exists to discharge, at the one claim the
whole revision rests on.

**And the pin is marked `INVERT-ON-BUILD` but cannot invert.** Mutant, applied to a scratch export
— the *fix* the headline demands, `_any_live` no longer blind to a live retired body, with
`_roster_live_sids` untouched exactly as §6.2 prescribes:

```
FLOOR sha256 : b76dc65d6007ba71e6c59dd47f6ac0502f92588466a22dfd1d1b5a2e4b50ef2c
=== FLOOR (clean scratch export) ===              32 passed in 4.33s

M-GATE2  _any_live also counts a keyed entry whose state is "done"
         (the defect the headline names, FIXED; _roster_live_sids unchanged)
  -> pytest -k TestTheShapeALingeringFinishedSessionPresents   4 passed, 28 deselected
  -> pytest tests/test_liveness_readers.py                     32 passed

restored sha256 == floor: True      real worktree bin/fleet.py untouched: True
```

**Fixing the defect changes nothing.** Every `INVERT-ON-BUILD` test in the headline class stays
green. §4's contract — *"a successor who unifies the readers and leaves this file green has not
landed the change"* — is therefore inverted at the headline: the file goes green whether or not
the change lands.

**The reason is structural, and it is in the branch's own build brief.** §6.2: *"`_roster_live_sids`
**stays, unchanged**, as the membership rule — `roster_liveness` wraps it"*, and §5.5: *"**Not**
deleting the `state != "done"` clause."* So after the entire §6 build, Q1 still answers
not-live for a live process at all 11 sites. **The headline defect is not fixed by the branch's own
build.** Yet §5.2 states the opposite: *"A correct patch applied to the wrong field is still the
wrong field, and that is the whole argument for §6.2 rather than for tuning the clause."* §6.2
delegates to the same field and returns the same answer.

That is the repeat-inference the brief asked about, in its precise form: **§7.9 names the trap
— *"the most dangerous inference is the one that confirms the correction you have just been
handed"* — and the immediately following draft installs a headline whose consequence is asserted
across a code path its instance cannot reach (M1), whose novelty is already documented in the file
(M3), whose instances are ordinary idle workers (M2), and whose pin cannot detect its own fix.
Naming the trap did not escape it.**

---

## THE F11 CONTEST, GRADED ON ITS MERITS — **PARTLY UPHELD**

The lane accepts F11 as to fact (revision 1's ordering claim lived in a gitignored mutable
journal; re-tagged BELIEVED) and contests the remedy: *"pre-registration inside a repo the
predictor controls is a convention, not a proof"*, and a real receipt *"would need an attestation
the lane cannot author — CI, or the fleet's own append-only `events.jsonl`."*

**1. Upheld — the timestamp half is correct.** `GIT_AUTHOR_DATE` / `--date` are author-controlled,
and a lane can author two commits in either order before publishing either. A commit *timestamp*
proves nothing about ordering. Correct, and worth having said.

**2. Rejected — the lane defends the wrong artifact.** What it actually built is not a timestamp
claim; it is a **DAG-ancestry** claim, and ancestry is structural, third-party checkable, and not
reorderable after the fact without changing both shas. MEASURED:

```
git show f9fa57e:docs/lanes/w50-live.md | grep "31 passed"   -> "**31 passed** on py -3.13 and py -3.10"
test defs at f9fa57e : 31        test defs at 74e3944 : 32
"test_the_union_gate_cannot_see_a_live_retired_body"  at f9fa57e: 0   at 74e3944: 1
git merge-base --is-ancestor f9fa57e 74e3944   -> f9fa57e IS an ancestor of 74e3944
```

The prediction's *content* is in the parent, the 32nd test is in the child, and the parent's sha is
sealed into the child. That is materially stronger than a mutable file and stronger than "a
convention". **The lane argues against the weaker of the two receipts it holds and never engages
the stronger one it created.**

**3. Rejected — the proposed alternative is inside the boundary it declares insufficient.**
MEASURED: `events.jsonl` is a plain file under `state_dir()` (`:318`) written by `append_event`
(`:1349`) — a library function in the same `bin/fleet.py` every lane imports. "The fleet's own
append-only `events.jsonl`" is authorable by any lane on this machine. A remedy that fails its own
test is not a higher bar.

**4. The consequence, which is why this matters beyond one row.** The lane's own MEASURED standard
is *"I ran it in this lane and read the output"* (`w50-live.md:13-14`). By the contest's logic that
is self-attestation too, and so is every receipt in `docs/specs/**` — `tools/verify_receipts.py`
runs inside the same trust boundary. **A rule demanding an attestation no lane can author does not
raise the bar for MEASURED; it abolishes the label for every lane in this campaign.** Do not adopt
it as stated.

**5. It is NOT a sophisticated way of declining a fix, and it should not be read as one.** The
lane *did* the thing — committed the prediction ahead of the run — and then argued about the label.
That is compliance plus a method proposal, which is the behaviour this campaign wants.

**Ruling:** F11's fact stands. The re-tag to BELIEVED is **over-conservative on this branch's own
evidence** — commit-DAG ancestry deserves better than a bare journal claim. The general rule the
lane proposes should **not** be adopted. What constrains the campaign is narrower than either
party stated: pre-registration is checkable when it is *ancestry*, not when it is a *timestamp*.

**And the miss is verified, to the lane's credit.** MEASURED, exactly as reported: `f9fa57e`
predicts 31 and contains 31 tests; `74e3944` contains 32, the addition being precisely
`test_the_union_gate_cannot_see_a_live_retired_body`. The lane **recorded the miss rather than
editing the prediction to fit.** That is the mechanism working, and it is the single best thing on
this branch.

---

## SPOT-CHECKS — ALL CLEARED

Two of the four mutants and the byte-identity claim, per the brief. Everything else in the
discharge's receipt block taken as read.

**CLEARED-1 — `bin/fleet.py` byte-identical.** MEASURED:

```
git rev-parse 4d78f6c:bin/fleet.py 74e3944:bin/fleet.py
  c759e8cadd09969ebb65ba53c0721bd39f967e2a
  c759e8cadd09969ebb65ba53c0721bd39f967e2a
git diff --stat 4d78f6c 74e3944 -- bin/fleet.py     -> (empty)
git diff --name-only 4d78f6c 74e3944 -> docs/lanes/w50-live.md, tests/test_liveness_readers.py
```

**CLEARED-2 — the floor reproduces exactly.** MEASURED, on a `git archive HEAD` scratch export:
`FLOOR sha256 b76dc65d6007ba71e6c59dd47f6ac0502f92588466a22dfd1d1b5a2e4b50ef2c` — **identical to
the digest §4.4 reports** — and `32 passed in 4.33s`. Both anchors asserted `occurrences == 1`
before any run.

**CLEARED-3 — M-D KILLED, and it is a genuine population test.** MEASURED. Planted the two-part
mutant from the test's own docstring (site 10's Q1 read relocated behind `_mutant_d_decoy`, plus a
compensating call), verified the textual `_roster_live_sids(` count was **unchanged**, then:

```
1 failed, 31 passed in 6.02s
FAILED ...TestTheCensus::test_roster_live_sids_call_sites_are_this_exact_POPULATION
restored sha256 == floor: True
```

Same figures the lane reports. The scope-multiset assertion does what §4.4 claims a count could
not.

**CLEARED-4 — M-A KILLED.** MEASURED. Deleted the stale-beat disarm
(`if age > SUPERVISOR_CLAIM_STALE_SECONDS: return`) from `_supervisor_gate`:

```
1 failed, 31 passed in 7.07s
FAILED ...TestWhatACanonicalAnswerMustPreserve::test_the_gate_arms_on_a_fresh_beat_and_disarms_on_a_stale_one
restored sha256 == floor: True
real worktree bin/fleet.py untouched: True
```

**CLEARED-5 — the mutation contract was honoured.** Both restores sha256-verified against the
floor; `git diff --quiet HEAD -- bin/fleet.py` clean after every run.

**CLEARED-6 — F11's prediction-miss account.** See the F11 section.

**MINOR m2 — but §6.6's "deliverable" is not committed.** §6.6: *"The mutation driver is a
deliverable, not a one-off … A successor adding a test to this file should add its mutant to that
ledger in the same commit."* MEASURED: the branch's diff is two files; there is no driver and no
ledger anywhere in the tree (`tools/` contains only `verify_receipts.py`). The mutant *definitions*
do live in the test docstrings, which is genuinely good and is how I reconstructed M-A and M-D —
but the harness that makes them re-runnable does not exist, so per this repo's own rule a pasted
`KILLED` remains a claim. I re-derived two of five in ~10 minutes; the other three stand on prose.

---

## FINDINGS, COLLECTED

| # | sev | finding | tag |
|---|---|---|---|
| B1 | **BLOCKING** | §6.1 (`:899`) instructs the successor to write the **retracted** mid-turn claim into `docs/specs/native-substrate.md`, citing the very section that retracts it and misdescribing the §0 table it points at. The near-miss the lane discloses at §7.9 is still armed. | MEASURED |
| B2 | **BLOCKING** | The headline claim's only pin re-implements the predicate and never executes `_cmd_respawn_supervisor`; marked `INVERT-ON-BUILD`, it **stays green when the named defect is fixed** (mutant M-GATE2, 32 passed). Structurally guaranteed by §6.2 keeping `_roster_live_sids` unchanged — so the headline defect survives the branch's own build, while §5.2 claims §6.2 is the answer to it. F3's defect class, at the claim F3's discharge installed. | MEASURED |
| M1 | MAJOR | The consequence names `_cmd_respawn_supervisor._any_live`; the instance is a **worker** record, which routes to `_cmd_respawn_native` and never reaches `_any_live`. Blindness true for supervisor records; the join is inferred. | MEASURED |
| M2 | MAJOR | All four `done`+live-pid instances are the workers' **CURRENT** sids and all four workers are **idle** — the ordinary resident state of an idle worker, which is the case the `done` clause was added to serve. §0's polarity is inverted; §5.2 prices it honestly, §0 does not. | MEASURED |
| M3 | MAJOR | "Two live sessions under one name from a retired fork" is already documented in `bin/fleet.py` (`:8509-8511`, `:9420-9424`) as a Steering-contract property, with retired-sid stop sweeps built at two sites as compensation. Presented as newly discovered and unguarded. | MEASURED |
| M4 | MAJOR | Retracted-draft residue at three further sites, **two inside the test file** (`:538` *"proceeds to stop … and mid-turn"* — false twice, driven; `:561` *"the roster got wrong"*), plus §5.5 (`:841-842`) contradicting §5.6 (`:875-877`) 34 lines later. | MEASURED |
| M5 | MAJOR | §3.0's account of the lane's own error ("from inside a busy session … structurally cannot contain the shape") is false — one inside-session snapshot found n=4. Duration, not detachment, was load-bearing; §3.6's lesson says so and §3.0 contradicts it. §3.5 ships the inert qualifier into a proposed `bin/fleet.py` docstring. | MEASURED |
| m1 | MINOR | The branch established pid **existence** (`tasklist`), never pid **identity**. Closed independently here (12/12 `claude.exe`, creation 1.4–2.7 s before `startedAt`); the conclusion survives, the receipt did not contain the step, and pid 4436 is now unverifiable. | MEASURED |
| m2 | MINOR | §6.6's mutation driver, called "a deliverable", is not committed; there is no ledger for a successor to add to. | MEASURED |
| m3 | MINOR | "Ordinary re-dispatch" under-enumerates: three sid-minting paths (`send` fork-steer, `resume-limited`, `respawn`-with-no-stop), two of which already sweep the parent. | MEASURED |
| m4 | MINOR | The state is a **window**, measured at ~1 h 56 m for `93f5c952` (process exit and key loss inside one ≤10 s interval); `multi_keyed` was empty in all 69 samples. §3.5's proposed docstring ("FALSE ON WIN32 IN BOTH DIRECTIONS … do not restore it") hands the successor a smaller truth than the one measured. | MEASURED |
| m5 | MINOR | F11 contest: fact upheld, remedy-contest **partly upheld** — right about timestamps, wrong about the DAG, and its proposed alternative (`events.jsonl`) is lane-authorable. Adopted as stated it abolishes MEASURED. | MEASURED |

---

## WHAT I DELIBERATELY DID NOT LOOK AT

Named, so the next reader knows the shape of the hole rather than inferring coverage:

* **Everything the first gate already covered and the discharge answered on receipts**: the
  11-site census, the heartbeat census, `_record_is_live`/§2.5, poll-not-push, both floors, the
  fence, §5's ruling, §6.2's predicate *design* (I attacked only its relationship to the headline
  claim), §6.5's re-pin numbers, disagreements 2 and 3.
* **The full-suite figure (4255 / 14 / 1) on both floors.** Taken as read per the brief. I ran
  only `tests/test_liveness_readers.py`, on `py -3.13` only.
* **Mutants M-B2, M-C, M-E.** Taken as read; I spot-checked M-A and M-D as instructed.
* **Whether the §6 build is worth doing.** Out of scope. B2 says the build does not fix the
  headline; it does not say the build is wrong.
* **Any posix behaviour.** No posix box.
* **The vendor's reason** for the ~2 h residency and the reaping at its end. Not fleet's business
  and not measurable from here.

---

## S. SAFETY — EXACTLY WHAT I RAN

* **Live fleet verbs: NONE.** No `status`, `peek`, `result`, `doctor`, `init`, or anything else.
* **Live reads only:** `claude agents --json --all` (1 inline + 69 from a detached sampler,
  10 s interval, self-terminating), `tasklist /FO CSV /NH`, `Get-CimInstance Win32_Process`, and
  **one read-only `open()`** of `C:\proga\claude-fleet\state\fleet.json` — a plain file read, no
  `fleet.lock`, no fleet verb, no write.
* `~/.claude/settings.json` and `~/.claude/fleet-homes.list` never opened for write. No
  `fleet init`, no `FLEET_HOME` export, no append to `fleet-homes.list`.
* **All mutation on a `git archive HEAD` scratch export** at `$CLAUDE_JOB_DIR/tmp/mut`, outside
  the repo. `occurrences == 1` asserted for every anchor before any run; floor green first; every
  restore proved by sha256 against the floor digest; `git diff --quiet HEAD -- bin/fleet.py`
  confirmed clean after each. **`bin/fleet.py` in this worktree was never written.**
* The three probe tests in Q2.4 live only in the scratch tree and are **not** committed to this
  branch; they are reproduced in full in `$CLAUDE_JOB_DIR/tmp/mut/tests/test_glive2_probe.py` and
  summarised above.
* `docs/lanes/w50-live.md` and `tests/test_liveness_readers.py` were **read, never edited**. The
  lane's artifacts are untouched evidence.
* Branch `w50/glive2` only. One commit, one file. No push, no merge, no other ref moved.
  `bin/fleet.py` byte-identical.
* Sampler processes (launcher pid 8288, python pid 44712) recorded in
  `state/journals/w50-glive2.md` and stopped before end of turn.
