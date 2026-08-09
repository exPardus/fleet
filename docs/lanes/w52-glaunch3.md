# w52 gate — adversarial gate on `w52/launch`, the stranger-clone rehearsal

**Lane:** `w52/glaunch3`, worktree `C:/proga/fleet-w52-glaunch3`, branch cut at `7c87730`
(= `w52/launch`'s tip). **Subject:** `docs/lanes/w52-launch.md`, 1010 lines, read in full.
**Mandate:** grade, do not repair. Nothing in this lane was fixed.

Every line is tagged **MEASURED** (I ran it on 2026-08-09 and the output is pasted or summarised
from a pasted run) or **BELIEVED** (reasoning or code reading).

---

## VERDICT: **GATING**

Not because the commit is unsafe — it is 1010 lines of `docs/lanes/`, it moves no code, and I
measured that it moves no pin either (§6). It is GATING because **the campaign is about to act on
this report**, and its load-bearing finding is graded on a property that does not replicate, with a
mechanism I could not observe once in six drives, and a proposed remedy that would reach twelve call
sites the report never looked at.

| | |
|---|---|
| **BLOCKING 1** | W52-2's proposed fix is unsafe and unscoped — `_roster_live_sids` has **13 call sites**, including the supervisor claim/release machinery. MEASURED. |
| **MAJOR 1** | W52-2's **HIGH** grade rests on *"deterministic, reproduced four times"*. I drove it six times and reproduced it **once**, in a state (`blocked`) the report never names. Real finding, wrong grade, wrong mechanism. MEASURED. |
| **MAJOR 2** | W52-2's key sub-claim — *"the fix that rescued macOS cannot fire on Windows"* — is **refuted**. It fires, and it is what makes 5 of my 6 drives succeed. MEASURED. |
| **MAJOR 3** | A **MEASURED** pasted receipt does not reproduce: `grep -n "user_settings_path()"` prints **4** lines on a byte-identical tree; the report pastes **3**. The finding it supports survives. MEASURED. |
| **MINOR 1** | W52-5's *"`0.00` is a value the code is explicitly written never to print"* overreaches. MEASURED. |
| **MINOR 2** | W52-3 names two overflowing statuses; there are **three**. MEASURED. |
| **MINOR 3** | The report makes **no suite claim at all**; the only floor evidence is an 8.3 % subset recorded in a gitignored journal. MEASURED. |
| **MINOR 4** | Non-claim #2 (statusline exit-0) was one command away from being a measurement. I ran it; it **holds**. MEASURED. |

**Findings W52-3, W52-4, W52-5, W52-6, W52-7 are CONFIRMED as findings**, at the grades the lane
gave them, with the two wording corrections above. **W52-1 is CONFIRMED and I strengthened it.**
The report is substantially right, unusually well controlled, and the single thing it most wanted
independently driven is the single thing that came back different.

---

## 0. Vantage — which tree every reading came from

The brief predicts this is the trap, so I measured the identity before reading anything into it.

**MEASURED.** I am standing on `w52/glaunch3` @ `7c87730a07eeccac2d2c1ac4dd001cc0d947c992`,
tree `2531b4d0c5349d51d234ef3de7901cb0d8beb6a9`, working tree clean.

```console
$ git diff --stat 64b43c2 7c87730
 docs/lanes/w52-launch.md | 1010 ++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 1010 insertions(+)

$ sha256sum bin/fleet.py
76b9bcbe50eac88eb72610683e0f6182c5ce3f33bf805c3b02056d83cd815d17 *bin/fleet.py
```

That hash is **the lane's own claimed hash for its clone**. So the lane's tree, `main` at `64b43c2`,
and my tree are the same `bin/fleet.py` bytes, and a code reading of mine is a reading about the
code the lane read. Its clone is gone; my clone is new (§1). **Every code line number below was read
in `C:/proga/fleet-w52-glaunch3/bin/fleet.py` at `7c87730`.** Every roster reading came from the
**live machine's** `claude agents --json --all`, which is machine-global and shared with the lane —
that is the one instrument where the lane and I are looking at the same object, five hours apart.

---

## 1. My fence, and the discriminator driven one arm further than the lane drove it

**MEASURED.** Legs (1) the clone's own shim with `FLEET_HOME` unset, (2) `CLAUDE_CODE_SESSION_ID`
removed. Real `~`, because credentials live there — I inherited the lane's W52-1 result rather than
re-discovering it. Precondition re-verified: `~/.claude/fleet-homes.list` **ABSENT**.

My clone is `…/jobs/4da64e3f/tmp/w52g3/clone/fleet` @ `7c87730`, `--no-hardlinks`,
tree `2531b4d0…` and `bin/fleet.py` `76b9bcbe…` — both identical to my worktree, measured.

A gate helper compared `fleet home` **normalised** and aborted on mismatch; it ran before every
fenced block, and it never fired.

### The 2×2 — shim × sid

The lane ran three arms. I ran the fourth, because a 2×2 is what isolates a variable:

```console
shim=CLONE  sid=REMOVED   -> C:/Users/Techn/.claude/jobs/4da64e3f/tmp/w52g3/clone/fleet
shim=CLONE  sid=RESTORED  -> C:/Users/Techn/.claude/jobs/4da64e3f/tmp/w52g3/clone/fleet
shim=LIVE   sid=REMOVED   -> C:/proga/claude-fleet
shim=LIVE   sid=RESTORED  -> C:/proga/claude-fleet
```

**MEASURED. The shim is the only variable that moves the answer; the sid moves nothing in either
row.** The lane's §1c conclusion — *the sid removal bought nothing here* — is **CONFIRMED**, and its
top-row half is unconfounded: the clone's registry has never heard of my session, so there is no
other route to the clone.

**And I must disclose that my new fourth arm is degenerate.** `LIVE/REMOVED` vs `LIVE/RESTORED` both
print the live home, but they cannot discriminate: my sid **is** registered in the live home's
registry, so a sid lookup and the install-root default both terminate at the same place. That arm
proves the sid does not *rescue* you from the live shim; it does **not** prove the sid lookup is
inert there. **BELIEVED**, and stated rather than dressed up: a clean test of the sid leg needs a
clone whose registry *does* contain the sid, which I did not build.

Three deliberate invocations of the **live** shim, all `fleet home`, all read-only, all disclosed —
`cmd_home` prints and returns; it took no lock and wrote nothing. Full command/home ledger in §8.

---

## 2. W52-2 — the HIGH. Driven six times. **The finding is real; the grade and the mechanism are not.**

This is the one the brief most wanted independently driven, and it is where this gate earns its keep.

### 2a. The documented invocation, on a healthy idle worker — **rc=0, five times out of six**

```console
$ fleet wait probe --timeout 300
probe: idle -- **Result:** hello.txt created in scratch dir, journal initialized. …
rc=0

$ fleet status
NAME                STATUS     TURNS     COST  MIN-AGO  MAIL   ATTACH  FLAGS
probe               idle           1        -        0     0        -  tokens:in=8 out=87

$ fleet respawn probe --yes
probe 48b0f708-9c0a-4f65-8285-360e841bb923 (native bg)
rc=0
```

Same `claude` version as the lane — **2.1.226**, MEASURED, so the version is not the discriminator.
Same platform, same OS, same machine, same account. Drives 1 and 2 (2 = the lane's exact sequence,
including a mid-turn `fleet send` that queued to the mailbox) both returned **rc=0**.

### 2b. My instrument is not blind — the positive control

Per the brief's rule about measurements whose good answer is a null: I ran the refusal against a
known-refusing input first.

```console
$ fleet status
probe               working        1        -        0     0        -  -
$ fleet respawn probe --yes
fleet: probe: turn is running -- pass --force to interrupt it first, or wait for it to finish
rc=1
```

**MEASURED.** The refusal is reachable by my harness. A drive that only ever printed `rc=0` would
have proved nothing.

### 2c. The roster entry is not the one the report pastes

The report's cause rests on this entry for the finished worker:

> `"status": "idle",` **`"state": "working"`**

I could not produce `state:"working"` on a finished session once. Immediately after `fleet wait`
returned idle:

```json
{
    "pid": 47812,
    "id": "df4f25a9",
    "cwd": "C:\\Users\\Techn\\.claude\\jobs\\4da64e3f\\tmp\\w52g3\\scratch",
    "kind": "background",
    "startedAt": 1786292845789,
    "sessionId": "df4f25a9-4354-439b-96fe-076e2c58ac45",
    "name": "fleet|probe|Create a file named hello.txt in the cur",
    "status": "idle",
    "state": "done"
}
```

**`state: "done"`.** And to answer the brief's "did the lane sample a window" directly, I polled the
roster 30 times over 60 s starting the instant the turn ended, recording every distinct shape:

```console
=== TIGHT ROSTER POLL for 60s ===
  sample #0 : state=done status=idle pid=present   <-- FIRST
--- distinct shapes observed over the 60s window ---
  state=done status=idle pid=present  (first at sample 0)
```

**MEASURED — one shape, no window, no transition.** `state:"working"` did not occur.

### 2d. And then it reproduced — in a **third** state the report does not name

I hypothesised the report's refusal came from the mail-driven second turn the Stop hook starts,
racing `fleet wait`'s return, and drove `respawn` with **zero delay** after `wait` returned, three
times:

```console
===================== RACE ITERATION 1 =====================
  roster: state=done status=idle pid=present
  status table: probe    idle    1    -    0    0    -    -
  RESPAWN rc=0

===================== RACE ITERATION 2 =====================
  roster: state=blocked status=idle pid=present
  status table: probe    idle    1    -    1    0    -    -
  RESPAWN rc=1
  RESPAWN out: fleet: probe: turn is running -- pass --force to interrupt it first, or wait for it to finish

===================== RACE ITERATION 3 =====================
  roster: state=done status=idle pid=present
  status table: probe    idle    1    -    1    0    -    -
  RESPAWN rc=0
```

**MEASURED. Iteration 2 is W52-2, reproduced.** `fleet status` says `idle`; `fleet respawn` says a
turn is running; the roster says `state:"blocked"`, `status:"idle"`, pid present.

**So the defect CLASS the report identified is real and I confirm it:** `_roster_live_sids` decides
liveness from key *presence* plus a single terminal state, never from `status`'s *value*, and a
finished Windows session can sit in a non-`done` state with both keys. That is exactly the report's
reasoning, and it holds.

**What does not hold:**

| Report's claim | My measurement |
|---|---|
| *"MEASURED, deterministic, reproduced four times across ten minutes"* | **1 of 6 drives.** Intermittent. |
| the entry sits at `state:"working"` | **Never observed.** 5/6 `done`; the one refusal was `blocked`. |
| *"Still `state=working status=idle` at T+8 min … Not a transient race."* | Unreproducible; 30 samples over 60 s show only `done`. |

**Grade: MEDIUM, not HIGH.** The HIGH rests on the word *deterministic*, and determinism is the part
that does not replicate. A stranger following the documented invocation gets a working `respawn`
most of the time; when they do not, the refusal message names the escape that works (`--force`) in
its own first clause. That is a real defect on the context-reset lever and it should be fixed. It is
not a HIGH. **The brief predicted this shape — "a finding that is real but MINOR dressed as HIGH" —
and it is right about the direction, one notch off about the size.**

### 2e. The docstring charge, read whole — and it is **backwards**

The brief instructed me to read the whole docstring, because *"a quoted fragment that changes meaning
in context is the finding."* Here it is entire:

```python
def _roster_live_sids(entries: list) -> set:
    """Sids whose backing process is LIVE. Contract rule
    (docs/specs/native-substrate.md, roster contract): `status`/`pid` keys
    exist only while the process lives; a lingering `state:"done"` entry
    (observed surviving >=3h21m) must NOT count as live, or a finished
    predecessor would block every successor claim for hours.

    posix-port live finding 2026-07-19 (macOS, claude 2.1.214): a finished
    bg session's host process can LINGER after its turn ends -- the entry
    keeps `pid` AND `status` ("idle") with `state:"done"`. The key-presence
    heuristic alone therefore misreads it as live (observed blocking
    `fleet respawn` on an idle worker). The documented terminal-state rule
    must dominate key presence: `state:"done"` is never live, keys or not.
    (On Windows the two conditions agree -- done entries lose pid/status.)"""
```

The report charges it with *"predicting this bug and then exempting the platform it happens on"*, and
grades the parenthetical *"half true"* on a census showing 90 `done` entries that lost both keys.

**MEASURED, on the live machine's 169-entry roster:**

```
   91  state='done'     status='(absent)'   pid ABSENT
   36  state='blocked'  status='(absent)'   pid ABSENT
   30  state='stopped'  status='(absent)'   pid ABSENT
    6  state='working'  status='busy'       pid present
    2  state='failed'   status='(absent)'   pid ABSENT
    2  state='(absent)' status=busy/idle    pid present
    1  state='blocked'  status='idle'       pid present
    1  state='done'     status='idle'       pid present
```

The report's count re-derives: **91**, not 90, and the roster has grown from 164 to 169 in the hours
between us, so that is agreement, not disagreement. **But the parenthetical is not "half true" — it
is simply FALSE, and the report's own evidence pointed the wrong way.** The 92nd `done` entry keeps
both keys:

```json
{"pid": 2604, "id": "cc6e9daf", "cwd": "C:\\proga\\fleet-w52-launch", "kind": "background",
 "startedAt": 1786290162980, "sessionId": "cc6e9daf-21c9-4f4b-bb0a-832f1c45fe5e",
 "name": "fleet|w52-launch|# w52 — the stranger-clone rehearsal, dr",
 "status": "idle", "state": "done"}
```

That is **the reporting lane's own session**, on Windows, `done`, holding pid and status. And every
finished probe I drove was the same shape (§2c). So on Windows, `done` entries **do** keep pid and
status while their host process lives — precisely the macOS shape the docstring describes.

**Which inverts the report's conclusion.** It writes:

> *"The fix that rescued macOS therefore cannot fire on Windows"*

**MEASURED false.** The fix — `state != "done"` dominating key presence — fires on Windows on every
one of my six drives, and it is exactly why five of them returned `rc=0`. Without it, all six would
have refused. The docstring does not *exempt* Windows from a fix; its parenthetical wrongly claims
the fix is unnecessary here, while the fix it introduces is load-bearing here. **The code is right,
the parenthetical is wrong, and the report got the direction of the error backwards.** The genuine
hole is narrower and neither document names it: **states that are neither `done` nor a running turn**
— `blocked`, measured; `working`, per the report — are counted live.

### 2f. **BLOCKING — the proposed remedy is unsafe, and its blast radius was never measured**

The report's BELIEVED fix: *"treat `state in ("done","stopped","failed")` **or** `status == "idle"`
as not-a-running-turn."* The brief asked me whether that breaks anything. It does.

**MEASURED — `_roster_live_sids` has 13 call sites, and `_cmd_respawn_native` is one of them:**

```console
$ grep -n "_roster_live_sids" bin/fleet.py
8270  8373  8392  8398  9559  9598  9914  10121  14869(def)  15393  15443  15673  18724  18772
```

Several are the supervisor claim/release machinery, which consumes this exact set to decide whether
a claim holder is still alive:

```python
    if (isinstance(claim, dict)
            and claim.get("released_by_sid") in _record_sids(record)
            and _releaser_live_sids(claim, _roster_live_sids(roster_entries),
                                    registry={"workers": {name: record}})):
```

**The hazard, MEASURED on live data.** My roster right now contains
`{"id": "3cb901f7", "name": "sup|inc-20260809T094210Z-5c4e|boot", "status": "idle",
"state": "blocked", "pid": 44232}` — a **supervisor**, process alive, `status:"idle"`. Under the
proposed `status == "idle"` clause that supervisor becomes **not live**, and a liveness test that
guards a claim would read an idle-between-turns claim holder as gone. The same clause reclassifies
two interactive sessions carrying `status:"idle"` and **no `state` key at all**.

Adding a disjunct to a set-builder consumed by twelve other decisions, one of which is "may another
supervisor take this claim", is not a minimal fix. **The report reasoned about one call site and
proposed a change to all thirteen.** REPORTED, not repaired.

The report is right to flag that a maintainer must decide whether `status` is contractual. On the
narrow question the brief asked: the docstring cites `docs/specs/native-substrate.md`'s roster
contract for **key presence** (*"`status`/`pid` keys exist only while the process lives"*). I found
no clause making `status`'s **value** contractual, and the report cites none. **BELIEVED** — a
`status`-value fix is building on an unpinned field, which is a second reason to scope it to
`_cmd_respawn_native` rather than to the shared helper.

### 2g. The closed-loop claim

*"`interrupt` → `respawn` → 'interrupt it first' is a closed R2 loop escapable only by `--force`."*
**CONFIRMED as code reading, BELIEVED as operator experience.** `fleet interrupt`'s success message
does name the bare `fleet respawn`, and the refusal does prescribe a wait that cannot end. But the
report's own sentence *"Both remedies the message offers are wrong"* is one remedy too strong:
`--force` is offered **first** in the refusal text and it works, measured by the report and not
contradicted by me. One of two remedies is wrong.

---

## 3. W52-4 — CONFIRMED, and the receipt under it does not reproduce

### The claim about the operator's machine: **CONFIRMED, MEASURED, READ-ONLY**

I read `~/.claude/settings.json` and wrote nothing. Its `statusLine` entry, verbatim:

```json
  "statusLine": {
    "type": "command",
    "command": "C:/Users/Techn/AppData/Local/Programs/Python/Python313/python.exe C:/proga/claude-fleet/bin/fleet_statusline.py",
    "refreshInterval": 10
  },
```

No double-quote characters; two space-separated tokens. **The live machine runs the pre-fix,
unquoted form.** CONFIRMED exactly as reported.

### The second half — no `doctor` row detects it: **CONFIRMED**

No `doctor` check reads the installed statusline. `cmd_doctor` (`bin/fleet.py:12565`) never reaches
`user_settings_path()`; the reachable references are the definition, a docstring, the chain-path
derivation, and `_install_statusline`.

### **MAJOR 3 — but the receipt that proves it is not what the command prints**

The report presents this as **MEASURED by exhaustive reference count**:

```console
$ grep -n "user_settings_path()" bin/fleet.py
353:def user_settings_path() -> Path:
6052:    return user_settings_path().with_name("fleet-statusline-chain.json")
6204:    path = user_settings_path()
```

Re-executed on a tree whose `bin/fleet.py` is byte-identical (`76b9bcbe…`, §0):

```console
$ grep -n "user_settings_path()" bin/fleet.py
353:def user_settings_path() -> Path:
6040:    DERIVED FROM `user_settings_path()` RATHER THAN RE-SPELLING `Path.home()`,
6052:    return user_settings_path().with_name("fleet-statusline-chain.json")
6204:    path = user_settings_path()
```

**Four lines, not three.** Line 6040 is inside a docstring, so the *conclusion* is untouched — it is
prose, not a call, and no `doctor` row is hiding there. But the word that fails is **exhaustive**,
and the failure mode is the one this repo keeps paying for: a pasted command with an output that is
not its output. I could not construct a grep on this tree that prints three lines — BRE prints four,
ripgrep's empty-group reading prints six.

**This is also my own coverage receipt (§7):** I found it by re-executing a pasted command instead of
reading it, which is the only technique that could have found it.

**Grade: MEDIUM is right, and arguably light.** A shipped fix that reaches no existing install, on a
surface no check inspects, is a permanent silent gap. I decline to raise it, for one measured reason:
the affected population is the intersection of "installed before the fix" and "spaced interpreter or
script path", and the report is honest that the second set is **BELIEVED**, reasoned from where
Windows puts user-scoped Python. Nobody has measured it. MEDIUM on a population nobody has measured
is the right call.

---

## 4. W52-5 — CONFIRMED line by line, five for five, with one sentence overreaching

The brief demanded line-by-line, because *"mostly fabricated" and "entirely fabricated" are different
findings*. The README block at lines 28–33 is quoted whole in the report and matches the tree.

**Tag census, with the positive control the rule requires** — a count whose good answer is 0 run
first against inputs whose answer is non-zero:

```console
\[mail\]         0        \[tool\]         2
\[assistant\]    0        \[text\]         2
                          \[user\]         2
                          \[user:meta\]    2
```

| README line | Verdict | Basis |
|---|---|---|
| `[tool] Read MIGRATION.md` | **UNEMITTABLE** | `:7126` is `f"[tool] {part.get('name', '?')}"` — name only, never arguments. MEASURED |
| `[tool] Write migrations/0042_users.sql` | **UNEMITTABLE** | same site |
| `[mail] delivered: "…"` | **UNEMITTABLE** | 0 occurrences, control non-zero. MEASURED |
| `[tool] Write migrations/0042_users.down.sql` | **UNEMITTABLE** | same site |
| `[assistant] Added the down-migration…` | **UNEMITTABLE** | assistant text renders `[text]` at `:7124`; `[assistant]` 0 occurrences. MEASURED |

**Five for five. "Entirely fabricated" is the correct characterisation**, and I close two holes the
report left open:

1. **Scope.** The report's phrase *"the shipped renderer"* invites "which renderer?". There is only
   one: `cmd_peek` calls `_cmd_peek_native` unconditionally, with no legacy branch. MEASURED.
2. **Were they ever true?** No.
   ```console
   $ git log --oneline -S '[mail]' -- bin/fleet.py      # (nothing)
   $ git log --oneline -S '[user:meta]' -- bin/fleet.py # control
   82a542d feat(native): claude-stop kill/interrupt + tombstones, peek/result rehome, …
   $ git log --oneline -S '[assistant] ' -- bin/fleet.py # (nothing)
   ```
   **MEASURED: `[mail]` and `[assistant]` have never existed in `bin/fleet.py` at any commit.** They
   are not substrate-pivot rot; they were invented. That is **stronger** than the report claims.

### MINOR 1 — the `0.00` sentence overreaches

The report: *"**`0.00` is a value the code is explicitly written never to print**, and the comment
says so."* The comment says so **for the native branch**. Fifteen lines on:

```python
        if is_native(rec):
            cost_s = f"{'-':>9}"
            …
        else:
            cost_s = _cost_cell(rec.get("cost_usd"))
```

`_cost_cell` returns `f"{cost:>{width}.2f}"` — which renders `0.00` for a cost of `0.0`. That branch
is live code, reached when `dispatch_kind != "bg"`, i.e. a **pre-pivot record** (`bin/fleet.py:1326`:
`"bg" = daemon-hosted; None = pre-pivot Popen`). Every spawn site sets `"bg"`, so nothing fleet can
spawn today reaches it. **The finding is right; the sentence is one clause too strong.** Correct
wording: *never printed for any worker fleet can spawn today.* MEASURED.

**Grade: MEDIUM, confirmed.** Untested, first thing a stranger reads, and `tests/test_doc_claims.py`
by its own docstring pins verbs/flags/counts — a sample transcript is none of those.

---

## 5. The LOW findings — all three CONFIRMED, one incomplete

**W52-3 (LOW) — CONFIRMED, and it is three statuses, not two.** `_text_cell` returns
`f"{…:<{width}}"`, a minimum width with no truncation; the header is `{'STATUS':<10}`. Measured
against the statuses the code sets (`NATIVE_TERMINAL_STATUSES`, `bin/fleet.py:3652`):

```
dead-suspected   len=14  overflows STATUS:<10 = True
over_ceiling     len=12  overflows STATUS:<10 = True     <-- not named by the report
interrupted      len=11  overflows STATUS:<10 = True
```

LOW is right. The report's enumeration is incomplete, which matters only if someone widens the
column to 12 on its authority. **MINOR 2.**

**W52-6 (LOW) — CONFIRMED, by the whole-tree grep the brief asked for**, not by the changed lines:

```console
$ grep -rn "not yet folded into" --exclude-dir=.git .
./CLAUDE.md:5:            … The superseded sentence said M-D and M-E were "not yet folded into §18", …
./docs/lanes/w48-launch.md:831: … (dated history, quoting)
./docs/lanes/w52-launch.md:786: … (dated history, quoting)
./docs/lanes/w52-launch.md:798: … (the report's own grep receipt)
./docs/launch-readiness.md:260:  … a line stale since `36a4c53`. This document opens by
```

The **only asserting** occurrence is `docs/launch-readiness.md:259–260`, which still tells the reader
CLAUDE.md's opening paragraph *"still reads"* the superseded sentence. CLAUDE.md:5 no longer does; it
quotes it in order to retract it. **The repair was not applied everywhere the claim appears.**
Sharpening the report's own point: `docs/launch-readiness.md` is **not** in `_HISTORICAL_PREFIXES`,
so it is a current-tree document by this repo's own exemption logic — a stale present-tense claim
there is exactly the class the exemption exists to keep held. LOW is right; it is one sentence.

**W52-7 (LOW) — CONFIRMED**, and it is three surfaces, not one. `bin/fleet.py:7817` prints
`fork-steered (new session {short_id})`. The idle case is described as "a new turn if idle" in
`README.md:148`, `docs/getting-started.md:282`, and `skills/fleet/SKILL.md:40` — none says the
session id changes. LOW is right: the worker **name** is the stable handle every fleet verb takes.

---

## 6. The floor — and the brief's construction worry does not fire here

**MEASURED. The full suite at `7c87730`, both interpreters, over the committed tree:**

```console
$ py -3.10 -m pytest -q
4621 passed, 14 skipped, 1 xfailed in 532.32s (0:08:52)

$ py -3.13 -m pytest -q
FAILED tests/test_fleet_index.py::TestTheSourceIsReadOnce::test_a_concurrent_writer_never_persists_a_torn_shard
1 failed, 4620 passed, 14 skipped, 1 xfailed in 567.38s (0:09:27)
```

**The 3.10 floor is GREEN.** The single 3.13 failure is an `IndexPathError` where `Path.resolve()`
returned an extended-length `\\?\C:\…` form for the file and a plain form for the base, inside a
*concurrent-writer* test. **Re-run in isolation: 3/3 pass on 3.13, 1/1 on 3.10.** It is a flake, and
it cannot be caused by `7c87730`, which touches one file under `docs/lanes/`. **BELIEVED** (from the
`\\?\` asymmetry and the concurrency): it is a real latent race in path normalisation worth its own
ticket. Not this lane's.

**Which subset the lane ran, and where the claim lives.** The brief attributes *"385 passed,
2 skipped on the 3.10 floor"* to the lane's evidence base. **That string does not appear in the
report at all** — I grepped it. It is in `state/journals/w52-launch.md:35–36`, which is gitignored
working state:

```
- `py -3.10 -m pytest tests/test_doc_claims.py tests/test_receipts.py tests/test_terminal_surface.py
  tests/test_lane_report_durability.py tests/test_views_doctrine.py -q -rs` → **385 passed, 2 skipped**
```

Five files. **MINOR 3: the report itself makes no suite claim.** 385 of 4636 collected is **8.3 %**.
The choice of five is defensible — they are the doc/receipt/surface pins a docs-only commit could
plausibly move — but a lane that lands a commit and records its only floor evidence in a disposable
file has put that evidence exactly where lane reports are pinned not to put things.

**Does `docs/lanes/` move the floor?** **No, and it cannot.** MEASURED:

```
64b43c2: tracked_md=155  CHECK_COUNT_DOCS=30
7c87730: tracked_md=156  CHECK_COUNT_DOCS=30
  new .md vs 64b43c2: ['docs/lanes/w52-launch.md']
```

```console
64b43c2 : 4636 tests collected
7c87730 : 4636 tests collected
```

`"docs/lanes/"` is the **first entry** of `_HISTORICAL_PREFIXES` (`tests/test_doc_claims.py:447`), so
`current_tree_docs()` excludes it and both `CHECK_COUNT_DOCS`-parametrised pins are unmoved.
**Collection is identical at both commits.** The brief's *"this docs-only commit may move the floor
by construction"* is **measured false for this commit** — correct as a general worry, inapplicable
here, and it would have been right had the report landed anywhere but `docs/lanes/`. This verdict
lands in the same exempt directory, so it cannot move the floor either.

---

## 7. The claims that are not findings

### The fence, and *"no single fence runs both halves"* — **CONFIRMED, and it is the report's best work**

I did not re-drive the credential half (the throwaway is gone and I inherited the result), but the
consequence is structural and I confirm it by construction: credentials live in the real `~`, fleet's
machine-global write targets are `~`-rooted, and one redirect cannot put them on opposite sides.
**BELIEVED, on a firm premise.**

**Why it was contained, not merely that it was.** The brief warned to assume this one has a false
stated reason too. I looked and did not find one: the report's mechanism — `INSTALL_ROOT` = the clone
⇒ population = `[clone]` ⇒ the sid lookup searches a registry that never heard of the session —
survives my own 2×2 (§1), and its precondition (an absent `fleet-homes.list`) I re-verified absent at
the start and the end of my own lane. **The report's stated mechanism is the one that holds.**

**What could the narrower Part-2 fence not have caught?** The report owes this census and does not
give it; the brief flagged it and it is the report's largest structural gap. Naming it: under legs
(1)+(2) with a real `~`, the fence cannot catch **any write to `~/.claude` that does not go through
one of fleet's three named path helpers**. `_install_statusline` is checked by absence-of-invocation,
not by containment; anything writing `~/.claude` under a fourth spelling of `Path.home()` would land
in the operator's real config and the report's audit table has no row that would see it. That is
narrow — I found no such spelling — but "my audit covers the three files I know about" is a different
statement from "nothing was written", and the report makes the second while measuring the first.
**BELIEVED.**

### The containment audit — **CONFIRMED, every line I can read**

MEASURED read-only on 2026-08-09 ~21:22, and I took the time-degrading half first per the brief:

| Artifact | Report | My re-measurement | |
|---|---|---|---|
| `~/.claude/settings.json` sha256 | `578BDE7B…D918` | `578BDE7B898C6011825E57BA9EFB23A75EB29E63E62382B957B45DC09133D918` | **match** |
| …size / mtime | 1859 / `2026-08-08T22:34:02.8541898+05:00` | 1859 / `2026-08-08T22:34:02.8541898+05:00` | **match** |
| `~/.claude/fleet-homes.list` | ABSENT | ABSENT | **match** |
| `~/.claude/fleet-statusline-chain.json` | ABSENT | ABSENT | **match** |
| live `state/worker-settings.json` | mtime `2026-07-30T08:12:18`, `642BDCBE…` | Jul 30 08:12, `642bdcbe171a8c75c50b974e68ac6d3df474ad00d2d5e0f623557fdef97ae196` | **match** |
| two `.bak`, a month prior | `2026-07-09T20:37:55`, `2026-07-13T19:45:31` | `09/07/26 08:37:55 PM`, `13/07/26 07:45:31 PM` | **match** |

**Is any probe session still alive?** No. MEASURED at 28 live `claude.exe`: all 16 carrying
`--settings` name `C:/proga/claude-fleet/state/worker-settings.json`; **zero** carry a temp-dir
settings path; **zero** run `-p`/`--print`; the remaining 12 are the Claude desktop app and
bg-pty-host wrappers. All five probe sids the report names are `stopped`/`done` **with no pid**.
**The audit is clean and I could not make it dirty.**

### The three non-claims — two correctly scoped, one that was one command from a measurement

1. **README line 81's "next tool boundary"** — correctly withheld. I did not observe a tool-boundary
   delivery either; my own mid-turn `send` also surfaced as Stop-hook feedback. **Correctly scoped.**
2. **The views exit-0 rule at the surfaces the rule names.** **MINOR 4 — this was cheap, and I ran
   it.** In my fenced clone, with a positive control first:
   ```console
   === POSITIVE CONTROL: healthy registry ===   [fleet]: no workers          rc=0
   === corrupt registry ({ this is not json) ===[fleet]: registry unreadable rc=0
   registry still present = True; content = { this is not json
   quarantine artifacts: 0
   ```
   **MEASURED: the statusline reads, renders, exits 0, and quarantines nothing.**
   `bin/fleet_statusline.py`'s `main()` returns 0 on every path, including
   `except BaseException: return 0`. **The rule holds at the statusline.** For the `/fleet:*` half:
   those are prompt templates, so "exit 0" has no direct referent — what they invoke is the CLI verb,
   which exits 1 by design and (report, MEASURED, uncontradicted) does not quarantine. **A refusal to
   claim that cost one command is a gap wearing humility**, and it happens to be the half that was
   still open.
3. **The space isolated in interpreter position** — correctly scoped. B1 does isolate the script
   position and the report says exactly that. Not re-driven by me; the spaced tree is a Part-3
   artifact I did not rebuild. **Declared uncovered, §9.**

---

## 8. Every command I ran, and which home it touched

MEASURED. Every fenced row was gated by `fleet home` compared normalised, before the block ran.

| Fence | Commands | Home actually touched |
|---|---|---|
| MY CLONE — legs (1)+(2), real `~` | `home` ×10, `init`, `spawn` ×6, `status` ×14, `status --json`, `wait` ×6, `send` ×4, `respawn --yes` ×6, `kill --yes` ×6, `clean --yes` ×6, `fleet_statusline.py` ×3 | `…/jobs/4da64e3f/tmp/w52g3/clone/fleet` |
| **LIVE shim, THREE times, deliberately** | `C:\proga\claude-fleet\bin\fleet.cmd home` ×3 | printed `C:/proga/claude-fleet`; read-only, no lock, no write |
| unfenced, read-only, machine-global | `claude agents --json --all` ×~40, `claude --version` | — |

Disclosed rather than buried: the three live-shim `home` calls are arms 3 and 4 of the discriminator
plus one control. `cmd_home` prints `Path(FLEET_HOME).resolve().as_posix()` and returns.

**Never run:** `fleet init` against the live home; any write to `~/.claude/settings.json`;
`fleet homes --add`/`--retire`; any `spawn`/`send`/`kill`/`respawn`/`clean`/`doctor --repair` against
the live home; any `claude plugin` mutation anywhere. My six probe sessions ran in a scratch dir
under my job directory and **all six are torn down** — registry `{"workers": {}}`, all six roster
entries `state:"done"` with no pid, verified after teardown.

**Disclosed cost, same as the report's:** six `--bg` haiku sessions wrote Claude Code's own state in
the real `~` (session records, roster entries, `daemon.log`). That is the sanctioned pattern and it
is the price of driving W52-2 at all.

---

## 9. My own coverage, measured rather than asserted

The brief asks for the equivalent of wave 48's withheld-defect technique. I do not have a second
party to withhold one, so I did the two things available.

**(a) Every measurement whose good answer was a null ran against a known non-null first.** Six
controls, all non-vacuous: the `respawn` refusal against a genuinely running turn (rc=1); the `[mail]`
tag census against four tags that do exist (2 each); `git log -S '[mail]'` against
`-S '[user:meta]'` (returns a commit); the statusline exit-0 against a healthy registry
(`[fleet]: no workers`); the fence gate against the live shim (prints the live home); the 3.13 suite
failure against three isolated re-runs.

**(b) The seeded defect found me.** The `user_settings_path()` receipt (§3) is a pasted MEASURED
receipt that does not reproduce on a byte-identical tree. The only technique that finds it is
re-executing rather than reading, and it is the single item here I would have missed had I graded the
report by reading it. That is my coverage evidence, and it is a receipt-class defect in a document
whose author is unusually careful about receipts.

**What I did NOT cover, so nobody reads this as broader than it is:**
- **Part 1 (quickstart steps 1–5) is ungraded.** The throwaway is gone; those receipts are
  unfalsifiable now. The brief told me to hunt the install half for missed findings, and I could not
  — the evidence was destroyed by design. **That is itself worth recording: a rehearsal that deletes
  its own tree cannot be gated on its central half.** The one install-half claim I could check
  independently, `README.md:136`'s two self-limits, is still present in the tree exactly as the
  report quotes it.
- **Part 3 (the spaced-path statusline differential) is ungraded.** Not rebuilt.
- The GitHub-shorthand marketplace form, untested by both of us.
- W52-4's affected population — still BELIEVED, by both of us.
- One machine, one OS, one `claude` version (2.1.226), same as the report. **My refutation of
  `state:"working"` is a Windows-10/2.1.226 refutation, not a universal one.**

---

## 10. WHERE THIS BRIEF WAS WRONG

**1. "It returns six findings, one HIGH." It returns SEVEN findings and TWO HIGHs.** MEASURED at the
report's own §10 ledger: W52-1 through W52-7, with **W52-1 graded HIGH** alongside W52-2. The brief
demotes W52-1 to "a claim that is not a finding" and the report's ledger does not. Since the brief's
whole first section asks whether a severity was earned by measurement or by framing, miscounting the
HIGHs is not cosmetic — it hid one of the two from the audit it was commissioning.

**2. The `385 passed, 2 skipped` floor claim is not in the report.** It is in the **gitignored
journal**. The brief calls the report "the evidence base" and then grades it on a sentence it never
contains. The real finding is the opposite one and I filed it: the report makes **no** suite claim.

**3. "This docs-only commit may move the floor by construction." It cannot.** `docs/lanes/` is the
first `_HISTORICAL_PREFIXES` entry; `CHECK_COUNT_DOCS` is 30 at both commits and collection is 4636
at both. The predecessor's lesson (a docs-only landing moving the floor by 4) is real and the
generalisation is wrong: it moves the floor only for docs **outside** the exempt prefixes.

**4. "Reproduce it yourself, or say plainly that you could not." I could, and the answer is worse
than either branch the brief anticipated.** It reproduces — once in six — in a roster state the
report does not name, by a mechanism the report gets backwards. The brief offered me "reproduced" or
"could not"; the useful answer was a rate and a different state.

**5. "That you can reproduce W52-2 at all inside a fence that costs you the credentials."** The
premise is confused: W52-2 lives in the *narrow* fence, which keeps the real `~` and therefore keeps
the credentials. There was never a tension. The report says so plainly in §1d and the brief inherited
the worry from the wrong half.

**6. "The severities are inflated rather than deflated" — right about W52-2, and it was your
sentence.** The brief that produced this lane pre-committed an outcome, and the lane returned a HIGH
graded on "deterministic" — the one property that does not replicate. I cannot prove the framing
caused it. I can say the load-bearing adjective is the false one, and that is the shape the brief
told me to hunt. **Symmetrically, and worth more:** the same framing aimed the lane at the use half,
and the two defects I found in the *install*-half reasoning (the inverted docstring reading, the
short grep receipt) are both in code and prose the lane treated as already-rehearsed territory.

**7. Where the brief was right, and it paid.** *"An instrument's answer is about the tree it is
STANDING IN"* — obeying it is what made §0 the first thing I did, and the `76b9bcbe…` identity is
what licenses charging a receipt with not reproducing. *"Run any measurement whose good answer is 0
against a known non-zero input first"* — without the positive control in §2b, five `rc=0` drives
would have been an untrustworthy null, and I would have had no basis to grade the HIGH. And *"quote
receipts whole"* found MAJOR 3 directly.

**8. One instruction I decline.** *"If you must cut, cut the LOW findings."* I did not need to cut,
and I would not have cut them here: W52-3's enumeration is incomplete and W52-6 is the second
generation of a drift this repo has now paid for twice. Cheap to confirm, and both got sharper under
a whole-tree grep. The expensive thing was W52-2, and it was expensive because it needed six live
drives — not because there were seven findings.

---

## 11. Findings ledger — this gate

| # | Class | Sev | Finding | Grade | Where |
|---|---|---|---|---|---|
| G1 | remedy | **BLOCKING** | W52-2's proposed `status == "idle"` fix is unscoped: `_roster_live_sids` has 13 call sites incl. supervisor claim/release; an idle-between-turns supervisor (`state:"blocked" status:"idle"`, pid alive) would be reclassified not-live | MEASURED | §2f |
| G2 | severity | **MAJOR** | W52-2 graded HIGH on *"deterministic, reproduced four times"*; 1 of 6 drives, in state `blocked`, never `working` — **MEDIUM** | MEASURED | §2a–2d |
| G3 | mechanism | **MAJOR** | *"The fix that rescued macOS cannot fire on Windows"* is refuted — `done` entries **do** keep pid+status on Windows, and the `state != "done"` guard is what makes 5/6 drives succeed | MEASURED | §2e |
| G4 | receipt | **MAJOR** | `grep -n "user_settings_path()"` prints 4 lines, not the 3 pasted, on a byte-identical tree; *"exhaustive"* fails. Finding survives | MEASURED | §3 |
| G5 | wording | MINOR | *"`0.00` is a value the code is explicitly written never to print"* — `_cost_cell` prints it for a pre-pivot record; true only for what fleet can spawn today | MEASURED | §4 |
| G6 | completeness | MINOR | W52-3 names 2 overflowing statuses; `over_ceiling` (12) is a third | MEASURED | §5 |
| G7 | evidence | MINOR | The report makes no suite claim; the only floor evidence is 8.3 % of the suite, in a gitignored journal | MEASURED | §6 |
| G8 | scope | MINOR | Non-claim #2 was one command from a measurement. I ran it: the statusline **holds** — rc=0, no quarantine | MEASURED | §7 |
| G9 | gap | MINOR | The report owes a "what the narrow fence could not have caught" census and does not give one | BELIEVED | §7 |
| — | — | INFO | W52-4, W52-5, W52-6, W52-7, W52-3 all **CONFIRMED at their graded severities** | MEASURED | §3–5 |
| — | — | INFO | The containment audit re-verifies on **every** line I can read, including the degrading one: no probe session is alive | MEASURED | §7 |
| — | — | INFO | W52-5 is **stronger** than claimed: `[mail]`/`[assistant]` never existed at any commit | MEASURED | §4 |
| — | — | INFO | The 3.10 floor at `7c87730` is GREEN (4621 passed); the lone 3.13 failure is a flake, 3/3 green in isolation | MEASURED | §6 |

**Nothing was repaired in this lane.** Every item above is REPORTED with the measurement that
licenses it and the file that would carry the fix.

**The honest state of the subject.** `w52/launch` is the most thoroughly controlled lane report I
have graded: its containment audit survives re-measurement line by line, its fence mechanism survives
a wider discriminator than it ran, and five of its seven findings confirm at the severity it gave
them — one of them more strongly than it claimed. Its one HIGH is the one that does not hold as
written, and it does not hold in a specific and instructive way: the lane read a docstring's
parenthetical as an exemption, when the measurement shows the parenthetical is false and the code it
apologises for is the thing keeping Windows working. **The report's headline sentence is that the
rehearsal has never once been run without finding something. That is still true — including of the
report.**
