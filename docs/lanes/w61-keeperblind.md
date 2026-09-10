# w61-keeperblind — why the keeper watched an 8h10m dark fleet and paged nothing

**Lane:** research/measurement. Branch `w61/keeperblind` from `036b21f`. No code changed; this file is
the deliverable. **Every line below is tagged MEASURED (I ran it, on this host, today) or BELIEVED
(inference, code reading, or someone else's report).** Host `kz-work`, Linux 6.8.0-139, `claude`
**2.1.267**, all roster observations 2026-09-10 04:27Z–04:40Z UTC unless stated.

---

## 0. LEAD: MY EVIDENCE CONTRADICTS THE BRIEF ON ITS CENTRAL QUESTION

The brief asks: *"is there anything in the roster that actually distinguishes a live body from a dead
one?"* — on the theory that if there is, the roster arm can be repaired.

**MEASURED: yes, `pid` separates live from dead perfectly (27/27 rows). And repairing the arm that way
would not have shortened this outage by one second.**

Because **efa0 was not dead.** MEASURED (`~/.claude/daemon.log:1395`): the supervisor's session process
was alive, holding a live pid, for the entire 8h10m window. It exited at `2026-09-10T04:05:58Z`, nine
minutes before the page. A liveness discriminator — however perfect — cannot page on a live body.

The rule is named `rule_supervisor_dead` and the fleet's actual failure mode is **`supervisor_stalled`**:
alive, listed, holding the claim, and not taking turns. **The keeper has no rule for that**, and the
roster arm — which is *correct code doing exactly its stated job* — is what stops the one rule it does
have from noticing.

**The discriminator that WOULD have worked is `status`, and it is already in the JSON the keeper
already parses, and `docs/specs/native-substrate.md` already tells you to use it.** MEASURED: an
idle-between-turns background session reads `status: "idle"`; a busy one reads `status: "busy"`; a
dead one carries no `status` key at all. Arming on `status == "busy"` instead of on mere presence would
have paged at **2026-09-09T21:04:36Z** — **7h10m51s earlier** (§7).

That is a **third option**, and it is not reading A. See §8 for why A's stated cost is not a cost, and
§9 for the failure mode that neither A, B, nor C fixes.

---

## 1. THE TWO CONTRADICTIONS IN THE BRIEF, RESOLVED FIRST

### 1a. `state` exists. Both parties were reading the same surface. (MEASURED)

The brief reports the supervisor probing `claude agents --json` and seeing keys
`['cwd','kind','name','pid','sessionId','startedAt','status']` with **no `state`**, while the interface
saw `state`. Neither was reading a different surface and neither mis-transcribed.

**MEASURED: roster rows are heterogeneous by `kind`, and the key set is per-row, not per-invocation.**

| `kind` | keys carried |
|---|---|
| `interactive` | `cwd, kind, name, pid, sessionId, startedAt, status` — **no `state`, no `id`** |
| `background` | `cwd, id, kind, name, sessionId, startedAt, state` (+ `pid`, `status` **only while the process lives**) |

The supervisor's quoted key list is **exactly and only** the interactive row's key set. BELIEVED (high
confidence, from the exact key-for-key match): the probe printed the keys of one row, and that row was
`fleet-e7` or `tap-b8`, the two interactive sessions. **The interface's report was correct.** This is
confirmed independently by `docs/specs/native-substrate.md` §"Roster contract", whose field-presence
table has carried the same per-`kind` split since the native-substrate spike.

**Method note this cost me nothing to obey and would have cost the supervisor an hour: never take
`keys()` of one row off a heterogeneous list.** I dumped the union of keys across all rows and the full
JSON of every row.

### 1b. The 8-vs-24 count gap is the terminal-state rows, and it is a stable rule (MEASURED)

`claude agents --json` (10 rows) vs `claude agents --json --all` (26 rows), 04:27:35Z, ten seconds
apart. **MEASURED, exact membership predicate, 0 mismatches over 38 samples / 1020 rows examined
(`roster-samples.jsonl`, 45 s cadence, 04:29:03Z–04:57:34Z):**

```
plain  =  { rows with state ∈ {"blocked", "working"} }  ∪  { kind == "interactive" }
--all  =  plain  ∪  { rows with state ∈ {"done", "failed", "stopped"} }
```

States ever seen in plain: `blocked`, `working`, `None` (interactive). States seen **only** in `--all`:
`done`, `failed`, `stopped`. The supervisor's 8-vs-24 and my 10-vs-26 are the same delta (16).

**This is the load-bearing fact of the whole outage** (§4): `blocked` is a **dead** state and it is in
the keeper's spelling.

---

## 2. THE ROSTER TRUTH TABLE (MEASURED)

All 26 rows of `claude agents --json --all` at 2026-09-10T04:27:36Z, plus the `w61probe` row I created
(§3). `pidchk` is `os.kill(pid, 0)` run by me at read time. `P` = present in the plain (keeper) spelling.

| sid8 | kind | state | status | pid | pidchk | started (UTC) | P | ground truth |
|---|---|---|---|---|---|---|---|---|
| `f83c8b56` | background | failed | – | – | – | 09-08T12:54:48Z | . | dead |
| `fc92acae` | background | done | – | – | – | 09-08T12:55:55Z | . | dead |
| `235f9dee` | background | failed | – | – | – | 09-09T03:50:17Z | . | dead |
| `f05d2308` | interactive | *(none)* | busy | 1755 | **ALIVE** | 09-09T05:56:38Z | **P** | live (interface) |
| `44701f95` | background | **blocked** | – | – | – | 09-09T06:22:24Z | **P** | **DEAD — sup 5ebc** |
| `1b0bd434` | background | stopped | – | – | – | 09-09T06:24:58Z | . | dead |
| `ff142a12` | interactive | *(none)* | idle | 8133 | **ALIVE** | 09-09T06:26:18Z | **P** | live (tap-b8) |
| `05e831eb` | background | stopped | – | – | – | 09-09T06:28:54Z | . | dead |
| `e367144f` | background | stopped | – | – | – | 09-09T06:29:00Z | . | dead |
| `376c8aa7` | background | done | – | – | – | 09-09T06:30:48Z | . | dead |
| `dad2e22f` | background | done | – | – | – | 09-09T06:30:53Z | . | dead |
| `b795b51c` | background | **blocked** | – | – | – | 09-09T06:31:01Z | **P** | **DEAD — w55-recon-b** |
| `0d61481c` | background | done | – | – | – | 09-09T07:07:31Z | . | dead |
| `62b44f5f` | background | done | – | – | – | 09-09T07:18:29Z | . | dead |
| `7c916110` | background | done | – | – | – | 09-09T08:08:01Z | . | dead |
| `c903f29a` | background | **blocked** | – | – | – | 09-09T16:29:31Z | **P** | **DEAD — sup 147a** |
| `3bcb8d1c` | background | **blocked** | – | – | – | 09-09T16:34:12Z | **P** | **DEAD — w58-notify** |
| `8136427d` | background | **blocked** | – | – | – | 09-09T16:34:19Z | **P** | **DEAD — w58-docs** |
| `f9b83beb` | background | done | – | – | – | 09-09T17:49:12Z | . | **DEAD — sup efa0, the outage** |
| `ffb7903b` | background | done | – | – | – | 09-09T17:56:09Z | . | dead |
| `a474be5a` | background | done | – | – | – | 09-09T18:02:06Z | . | dead |
| `68da197a` | background | done | – | – | – | 09-09T18:02:15Z | . | dead |
| `73544cd0` | background | failed | – | – | – | 09-09T19:18:52Z | . | dead |
| `27e3e17d` | background | working | busy | 298506 | **ALIVE** | 09-10T04:15:03Z | **P** | live (sup 2382) |
| `f2ee02cc` | background | working | busy | 302909 | **ALIVE** | 09-10T04:27:06Z | **P** | live (this lane) |
| `3409a1f9` | background | working | busy | 302971 | **ALIVE** | 09-10T04:27:16Z | **P** | live (w61-sidcollision) |
| `b594aef5` | background | working | **idle** | 303182 | **ALIVE** | 09-10T04:33:13Z | **P** | **live, IDLE between turns** (§3) |

### Which fields discriminate? (MEASURED, n = 27)

| candidate | separates live from dead? | verdict |
|---|---|---|
| **`pid` present** | **27/27, no exceptions.** Every row with a `pid` → process ALIVE. Every row without → no process. | **PERFECT here.** Useless for this outage (efa0 had one). |
| `status` present | 27/27, identical partition to `pid` (they co-occur). | Same. |
| **`status == "busy"`** | separates **busy** from *(idle-alive ∪ dead)* — **this is the useful cut** (§7) | **the discriminator nobody tried** |
| `state == "working"` | 27/27 here, **but see the caveats** | **UNSAFE** — see below |
| `state ∈ {done,failed,stopped}` ⇒ dead | 27/27 | true but incomplete: **misses `blocked`** |
| `state == "blocked"` ⇒ ? | 5 rows, **all 5 dead** here | **AMBIGUOUS by contract** — see below |
| `sessionId` present (**what the keeper uses**) | **0/27.** Every row has one. | **no information at all** |
| `startedAt`, `cwd`, `kind`, `name`, `id` | 0/27 | no information |

**One precision the next implementer needs (MEASURED):** on a dead row the `status` and `pid` keys are
**absent from the object**, not present-and-null. All five `blocked` rows carry exactly
`['cwd','id','kind','name','sessionId','startedAt','state']`. So `"status" in e` (the predicate
`fleet.py` already uses) is correct, and `e["status"] is None` would raise. The interface's report of
`status: null` was a rendering of absence, not a value in the JSON.

**Why `state` alone is unsafe, three ways, all with receipts:**

1. **`blocked` is dead here and live elsewhere.** `docs/specs/native-substrate.md` documents two live
   `blocked` shapes: a consumed Stop-block (`status: "idle"` + `pid`) and a permission-gate stall
   (`status: "waiting"`, `waitingFor: "permission prompt"`, + `pid`). My five `blocked` rows carry
   **neither** `status` nor `pid` — a **third shape the spec's table does not have a row for** (§10).
2. **`working` is not liveness.** The spec's table has a `state: "working"` — **wedged, never started a
   turn (G8 stdin hazard)** row with no `pid` and no `status`. And `bin/fleet.py:3663`
   (`_dispatch_grace_active`) records a measured live finding: a freshly dispatched bg session is
   **state-only `{'state':'working'}`** for its first seconds.
3. **`working` is not busy.** MEASURED, §3: an idle-between-turns session stays at `state: "working"`.

**MEASURED CONCLUSION for the brief's question: the roster arm is not inert — it is *unfiltered*.
There is plenty in the roster that distinguishes a live body from a dead one. The keeper reads none
of it.**

---

## 3. THE DECISIVE EXPERIMENT: what an idle-but-alive background session looks like

Nothing in the historical record shows a background session *between* turns, and the whole argument
turns on it. So I made one, in an **isolated `FLEET_HOME`** (`$TMPDIR/w61/home`, `fleet init` + `fleet
spawn`, haiku, trivial prompt) — the live registry, claim and `supervisor/` were never touched (§12).

MEASURED, `claude agents --json --all` every 13 s:

```
04:33:21Z  state=working status=busy pid=303182 procchk=ALIVE     <- in its turn
04:33:34Z  state=working status=idle pid=303182 procchk=ALIVE     <- turn ended
04:33:47Z  state=working status=idle pid=303182 procchk=ALIVE
   ... 8 more identical samples through 04:35:45Z ...
04:38:17Z  state=stopped status=None pid=None                     <- after `fleet kill`
```

**MEASURED: an idle-between-turns background session is `state: "working"`, `status: "idle"`, live
`pid`. It is PRESENT in the roster, in both spellings, and it stays that way.**

Three consequences, and the second one kills the obvious fix:

1. **`status` is the busy/idle axis and it works.** `busy` → `idle` was observed within 13 s of the
   turn ending, with no other field moving.
2. **`fleet.py`'s own live predicate would NOT have helped.** `_roster_live_sids` (`bin/fleet.py:15821`)
   is `("status" in e or "pid" in e) and state != "done"`. An idle-alive session satisfies both clauses,
   so `f9b83beb` would have counted as **live** for all 8h10m and the arm would have suppressed just the
   same. **BELIEVED (high): swapping the keeper's `_agents` for fleet's live-sid predicate is a
   one-line change that fixes nothing about this outage.** I flag it because it is the fix any reader
   of §5 will reach for first.
3. **The C2 docstring's premise is inverted** (§6).

---

## 4. WHAT REMOVED efa0's ENTRY — AND THE NUMBER THE BRIEF ASKED FOR

The brief: *"If entries are removed on a timer, the keeper's blindness has a bounded duration and that
duration is the single most decision-relevant number you can produce."*

**MEASURED, from `~/.claude/daemon.log` — there is a timer, it is 8h, and it is `idle`-anchored:**

```
[2026-09-10T04:05:58.064Z] [bg] bg retire f9b83beb: settled, idle 8h
[2026-09-10T04:05:58.871Z] [bg] bg settled f9b83beb (done)
[2026-09-10T04:06:03.887Z] [supervisor] shutting down (cause=idle_exit, uptime=546s, leases=0, live_workers=0)
```

(`[supervisor]` there is the **claude daemon's** supervisor thread, not fleet's supervisor tier. Two
unrelated things called "supervisor" in one incident — worth a name in any follow-up.)

Corroborating, independently: the transcript `~/.claude/projects/-home-altai-proga-fleet/f9b83beb-….jsonl`
has mtime `2026-09-10T04:05Z` (MEASURED). `state/events.jsonl` records nothing about the exit — its
only efa0 line in the window is `status_changed working→idle` at **04:14:50Z**, *fourteen seconds after
the page*, i.e. it is the interface's post-relaunch `fleet status` recompute, not the cause. **The
brief was right that `state/events.jsonl` does not explain it; it is explained in `~/.claude/daemon.log`.**

### But the 8h bound is NOT the answer, because it does not always hold (MEASURED)

Every daemon retirement on this host, cross-checked against the row's state in the roster **right now**:

| sid8 | retire reason | idle | retired at (UTC) | roster `state` today | in plain? |
|---|---|---|---|---|---|
| `b795b51c` | **idle-prompt** | 8h | 09-09T14:45:26Z | **blocked** | **YES** |
| `376c8aa7` | settled | 8h | 09-09T14:46:26Z | done | no |
| `dad2e22f` | settled | 8h | 09-09T14:52:26Z | done | no |
| `62b44f5f` | settled | 8h | 09-09T15:40:26Z | done | no |
| `0d61481c` | settled | 8h | 09-09T15:52:26Z | done | no |
| `7c916110` | settled | 8h | 09-09T16:17:26Z | done | no |
| `44701f95` | **idle-prompt** | 8h | 09-09T16:18:26Z | **blocked** | **YES** |
| `8136427d` | **idle-prompt** | 8h | 09-10T01:06:54Z | **blocked** | **YES** |
| `3bcb8d1c` | **idle-prompt** | 8h | 09-10T01:36:55Z | **blocked** | **YES** |
| `c903f29a` | **idle-prompt** | 8h | 09-10T01:50:55Z | **blocked** | **YES** |
| `f9b83beb` | **settled** | 8h | 09-10T04:05:58Z | done | no |

**MEASURED, 11/11, no exceptions: `settled` → `done` (leaves the keeper's list). `idle-prompt` →
`blocked` (stays in the keeper's list, apparently forever).** The daemon logs `bg settled X (done)`
for both — the disposition that decides the roster literal is the *retire reason*, not that line.
(The oldest `blocked` row, `44701f95`, has been dead and listed for **22h05m** as of 04:27Z. No
expiry observed. BELIEVED: none exists — `--all` still lists a `done` row from 09-08T12:54Z, 39h old.)

**Therefore — and this is the number the operator actually needs:**

> **The keeper's blindness to a stalled supervisor is bounded at 8h + one tick ONLY IF that supervisor's
> session retires `settled`. If it retires `idle-prompt`, the blindness is UNBOUNDED.**
>
> **MEASURED: 2 of the 3 retired supervisor bodies on this host (`5ebc`, `147a`) retired `idle-prompt`
> and are `blocked` in the keeper's spelling right now. efa0 got the lucky disposition.**

BELIEVED (medium — correlation is 11/11 but I did not isolate the cause): `idle-prompt` is the daemon's
name for a session parked at its input prompt, which is also the state `native-substrate.md` G1-sharp
attributes `blocked` to (a consumed Stop-block). Fleet's own Stop hook can issue `decision: "block"`,
so fleet workers routinely pass through it. I did not run the experiment that separates "retired at an
idle prompt" from "last Stop was blocked"; a follow-up wanting to *predict* the disposition needs it.

---

## 5. THE MECHANISM, IN ONE PAIR OF QUOTES

`bin/fleet_keeper.py:392` — **every row's sid, unconditionally:**

```python
    sids = set()
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("sessionId"), str):
            if row["sessionId"]:
                sids.add(row["sessionId"])
```

`bin/fleet.py:15821` — **the same repo, the same surface, filtered:**

```python
    return {
        e.get("sessionId") for e in entries
        if isinstance(e, dict) and isinstance(e.get("sessionId"), str)
        and e.get("sessionId") and ("status" in e or "pid" in e)
        and e.get("state") != "done"
    }
```

`bin/fleet.py:3775` (`recompute_worker_native`) goes further and reads the **third** value the keeper
never looks at:

```python
        rstatus = entry.get("status")
        if rstatus in ("busy", "waiting"):
            updated["status"] = "working"
```

**MEASURED (code read, three call sites): fleet has a three-way roster read — live+busy, live+idle,
dead/gone. The keeper has a one-way read: `sessionId` present.** `obs["claim_sid_live"]` is therefore
not a liveness fact; it is `claim_sid is not None`, plus the near-certainty that the CLI still has a
row for it.

---

## 6. THE DOCSTRINGS, GRADED

**`_agents`, `bin/fleet_keeper.py:392`:**
> *"`claude agents --json` lists the ACTIVE sessions; the sids are the identity join C2 replaced the
> name prefix with."*

**GRADE: FALSE, and load-bearing.** MEASURED: at 04:27Z the plain spelling returned 10 rows, of which
**5 were dead bodies** (`44701f95`, `b795b51c`, `c903f29a`, `3bcb8d1c`, `8136427d`), the oldest dead
and listed for 22h05m. "ACTIVE" describes 5 of 10 rows. The word doing the damage is `ACTIVE`: it tells
the next reader that membership *is* liveness, so no caller filters.

**`rule_supervisor_dead`, `bin/fleet_keeper.py:151`:**
> *"`claude agents --json` lists ACTIVE sessions only, so an idle-between-turns supervisor is absent
> from it while perfectly alive -- fleet's own verdict engine reads roster-absence plus a fresh outcome
> as `idle`, not dead -- and a name join is the weaker proof anyway (ai-title can overwrite `name`
> after a resume)."*

Graded clause by clause:

| clause | grade | evidence |
|---|---|---|
| "lists ACTIVE sessions only" | **FALSE** | §2: 5/10 plain rows dead |
| "an idle-between-turns supervisor is **absent** from it while perfectly alive" | **FALSE — inverted** | §3: idle-between-turns is **present**, `state: "working"`, `status: "idle"`, live pid |
| "fleet's own verdict engine reads roster-absence plus a fresh outcome as `idle`, not dead" | **TRUE** | `recompute_worker_native` branch 4 (`bin/fleet.py:3789`) |
| "a name join is the weaker proof anyway (ai-title can overwrite `name` after a resume)" | **TRUE, and still true** | see §8 — do not discard this |

**The premise is exactly inverted, and the inversion is why the arm is the wrong shape.** The arm was
built to protect a supervisor that is *alive and unlisted*. MEASURED: that state does not occur for a
background session on this host — alive means listed. What occurs is the opposite: **dead and listed**
(5 rows) and **alive, listed, and doing nothing** (efa0, 8h10m). The arm admits both.

**Not graded false:** the C2 change itself. Replacing the `sup|` name-prefix join with a session-id
join was right, and §8 says why the arm must not simply be deleted.

---

## 7. WHAT A `status`-ARMED RULE WOULD HAVE DONE (arithmetic, MEASURED inputs)

MEASURED inputs: `state/keeper/last-page.json` records the one page at epoch `1789013675.385` =
`2026-09-10T04:14:35Z`, with `heartbeat_age_seconds = 29451` at that observation (the brief's driven
value, which I reproduced). `HEARTBEAT_STALE_SECONDS = 3600`.

- last supervisor heartbeat: **2026-09-09T20:03:44Z**
- heartbeat crosses stale: **2026-09-09T21:03:44Z**
- first keeper tick at or after that (MEASURED, `journalctl --user -u fleet-keeper.service`): **2026-09-09T21:04:36Z**
- page actually sent: **2026-09-10T04:14:35Z**

**Detection would have moved 7h10m51s earlier. The dark window would have been ≤1h16m (the 1h stale
threshold + ≤16m of tick latency) instead of 8h10m51s.**

The keeper ticked at ~16-minute intervals with no gaps across the whole window (MEASURED, ~31 ticks,
all `Finished … Consumed ~1.2s CPU`, none printing anything until `09:14:36+05:00` = `04:14:36Z`
`keeper: paged supervisor-dead`). **The timer was never the problem.**

---

## 8. THE SECOND RULE WITH THE SAME SHAPE — AND THE REST OF THE AUDIT

I drove all nine rules as pure functions (`evaluate()` on hand-built observation dicts; **the keeper
binary was never run, `--dry-run` or otherwise, and `state/keeper/last-page.json` was never written**).

### 8a. The elimination the brief asked me to re-derive (MEASURED, driven)

Flipping one key at a time out of the outage observation:

| flip | `rule_supervisor_dead` | `evaluate()` (all nine) |
|---|---|---|
| `goals_active=False` | None | **SILENT** |
| `agents_ok=False` | None | pages **login-expired** |
| `claim_state="unknown"` | None | pages **claim-unknown** |
| `heartbeat_age_seconds=60` | None | **SILENT** |
| **`claim_sid_live=False`** | **PAGE** | pages **supervisor-dead** |

- `agents_ok=False` and `claim_state="unknown"` are excluded because **each would have produced a
  different page**, and `state/keeper/last-page.json` carries exactly one entry (`supervisor-dead`,
  `1789013675.385`) and the unit log carries exactly one `keeper: paged` line (MEASURED).
- `goals_active=False` is *not* excluded that way — it is silent everywhere. It is excluded twice
  instead: `grep -c SUPERVISOR-DORMANT supervisor/GOALS.md` = **0**, and `supervisor/GOALS.md` has
  mtime `2026-09-08 17:40:42 +0500` and its last commit is `3ccb2d5` — **unchanged across the entire
  window**, while the 04:14:35Z page itself *requires* `goals_active` true.
- `heartbeat_age_seconds` grows monotonically, so it was >3600 from 21:03:44Z on.

**MEASURED: the brief's suppressor is confirmed. `claim_sid_live` is the only silencer.**

### 8b. `rule_worker_anomaly` — a second blindness, different shape, same consequence

`ANOMALOUS_STATUSES = ("dead-suspected", "limited")`. MEASURED, live `fleet.status_snapshot()` at
04:31Z: 21 workers, `by_status = {dead: 4, idle: 14, working: 3}`. **Neither anomalous status is
present anywhere in the fleet**, including on `sup|…5ebc` and `sup|…147a`, whose bodies are `blocked`
corpses, and on `w58-docs`/`w58-notify`, likewise dead.

Driven (MEASURED):

| observation | result |
|---|---|
| all workers `idle` (today's actual shape) | **SILENT** |
| one worker `status: "dead"` | **SILENT** |
| one worker `dead-suspected` | PAGE |
| `idle` + `mail > 0` | PAGE |

**MEASURED: `status_snapshot()` reads the registry and never the roster** (`bin/fleet.py:5661`); the
`dead-suspected`/`limited` verdicts are written only by `recompute_worker_native`, reached only from
lock-holding verbs (`fleet status <name>`, `wait`, `respawn`, …). **The keeper runs none of them.**

> **The structural defect, stated once, covering both rules: the keeper never causes a liveness
> computation. It reads values other processes wrote, and when the fleet goes dark, no other process
> is running to write them.** That is why a dark fleet is exactly the condition under which the
> keeper's observations go stale — and `rule_worker_anomaly` is a rule that can only report anomalies
> somebody else already found.

### 8c. Every rule, and what silences it (MEASURED, driven)

| rule | gates | silenced by |
|---|---|---|
| `rule_registry_unreadable` | `registry_ok` | **key absent → default `True` → silent** |
| `rule_claude_missing` | `agents_missing` | key absent → silent |
| `rule_login_expired` | `agents_ok` AND `not agents_missing` | **`agents_ok` absent → default `True` → silent** |
| `rule_claim_unknown` | `goals_active` AND `agents_ok` AND `state=="unknown"` | either gate false → silent (`agents_ok=False` correctly hands off to `login-expired`; `goals_active=False` silences **absolutely**) |
| `rule_supervisor_dead` | `goals_active` AND `agents_ok` AND (state) AND (stale beat) AND **NOT `claim_sid_live`** | §8a |
| `rule_supervisor_frozen` | `pending_decision` | single gate — clean |
| `rule_worker_anomaly` | worker status ∈ 2 literals, or idle+mail | §8b |
| `rule_unpushed` | `n>0` AND `oldest is not None` AND age ≥ 6h | **`_git_unpushed` returns `(0, None, None)` on any failure → silent**; and `n=19, oldest=None` → **silent** |
| `rule_hook_errors` | `cur > prev` | **log truncation/rotation (`900 → 3`) → silent, and stays silent until the count re-passes the old high water mark** |

**MEASURED: `evaluate({})` on an empty observation returns `[]`.** A total collection failure pages
nothing at all. Every rule but `claude-missing` and `supervisor-frozen` is **fail-silent by default**.
That is a deliberate anti-false-positive posture (fix wave 1 I1/I2 are explicitly about it) and it is
the same posture that produced this outage; I name it without recommending a wholesale inversion.

**Two further AND-shaped silencers worth a follow-up, both `goals_active`:** it gates *both*
`rule_claim_unknown` and `rule_supervisor_dead`, it is read from `status_snapshot()["supervisor"]
["goals_active"]`, and a `False` there silences the fleet's only two supervisor-liveness rules with no
page of any kind. A malformed or truncated `supervisor/GOALS.md` is a **silent** total loss of
supervisor monitoring.

---

## 9. WHICH OF A / B / NEITHER — AND WHAT EACH COSTS

**Recommendation: neither A nor B as written. Do C first — it is small, it is testable, and both A and
B still need it. Then do B. A is a trap, but not for the reason the gate says.**

### C — arm on `status`, not on presence *(new; the measurement supports it)*

Replace `claim_sid in roster_sids` with `the claim's row exists AND reads status == "busy"`.

- **Cost of the false positive it introduces:** a supervisor mid-turn for over an hour, whose heartbeat
  went stale during that one long turn, reads `status: "busy"` and is still suppressed. **No new false
  positive.** The 8h10m outage pages at 21:04:36Z (§7).
- **What it costs elsewhere:** MEASURED — `status` is absent on every dead row, so a dead body pages
  (correct), and `waiting` (permission stall, per the spec's table) would page too. **BELIEVED (high):
  that is correct behaviour for a headless fleet** — a supervisor blocked on a permission prompt with
  nobody at the keyboard is exactly as stalled as a dead one.
- **Residual I could not close:** a session **wedged mid-turn** would report `status: "busy"` forever
  and suppress forever. UNMEASURED — I did not produce a wedge. This is the one hole C leaves, and it
  is strictly smaller than today's.
- **It keeps the thing C2 bought.** The sid join stays; only the membership predicate changes. **This
  matters and is the brief's own warning: reading A ("drop the roster arm") throws away C2's fix for
  the `sup|` name-prefix join, whose false positive was real — `ai-title` can overwrite `name` after a
  resume, so a name join can bind a live supervisor to the wrong row or fail to find it and page
  `supervisor dead` at a healthy fleet.** C is the version of A that does not pay that bill.

### A — drop the roster arm so a stale heartbeat alone pages

**The gate records A's cost as "a supervisor merely idle between waves pages too". MEASURED, I think
that cost is mis-stated, and the operator should know before choosing.** `HEARTBEAT_STALE_SECONDS` is
3600 and the heartbeat refreshes on every turn. A supervisor that has taken **no turn for over an
hour** is, on this host's evidence, not "merely idle between waves" — it is the outage. There is
already a sanctioned way to say "deliberately not supervising": the `SUPERVISOR-DORMANT` token in
`supervisor/GOALS.md`, which clears `goals_active` and silences the rule outright (MEASURED, §8a).

So A's real cost is not noise — it is **losing the C2 guard against a wedged-but-working supervisor**,
and it makes the rule blind to nothing. **A is C minus the safety.** If the operator wants A's
simplicity, take C: it is the same page, one field cheaper in risk.

### B — give the supervisor a wake mechanism so it never sits idle-but-listed

**Supported, and it fixes something C cannot: C detects the stall, B prevents it.** Note what B is
actually up against, MEASURED in §4: the daemon retires an idle bg session at **8h**, so a wake
mechanism must fire well inside 8h or the body is gone anyway; and `~/.claude/daemon.log` shows the
daemon itself exiting `cause=idle_exit` at 04:06:03Z with `live_workers=0`. **B's real cost is that it
is a new always-on mechanism whose own failure is silent** — which is precisely the failure class this
report is about. **B without C is B unmonitored.** Do C first so B has a watchdog.

### Not in scope, but the operator should see it

`state: "blocked"` corpses sitting permanently in `claude agents --json` while `done` corpses are
filtered out looks like a CLI defect, not a fleet one (MEASURED, §4: 5 rows, one 22h05m old,
`idle-prompt` retirements). **Any fleet-side fix has to survive it, because it is upstream of us and
it is what makes today's blindness potentially unbounded.**

---

## 10. WHAT I MEASURED THAT THE SPEC DOES NOT YET SAY

`docs/specs/native-substrate.md` §"Roster contract" carries a field-presence-per-state table. My
measurements **confirm** its `status`/`state` disjoint-axes rule and its startup-transient amendment,
and **extend it in two places** (both at `claude` 2.1.267 / Linux; the table's rows are pinned at
2.1.207–2.1.214 / macOS):

1. **A `state: "blocked"` row with NO `pid` and NO `status`.** The table has two `blocked` rows, both
   with `pid` **Y** and `status` **Y**. MEASURED: 5 such rows here, all with both absent, all dead,
   produced by `bg retire …: idle-prompt, idle 8h`. **Third `blocked` shape.**
2. **`state: "working"` + `status: "idle"` + live `pid` = idle between turns, persisting.** The table
   pairs `status: "idle"` with `state: "done"` — "process still briefly live". MEASURED here it is
   `state: "working"`, and it is not brief: it persists until the 8h retire.

The spec's own design rule is the one the keeper breaks, and it is already written down:

> *"a status surface must inspect both fields together, never `state` alone"* — and, from the G1
> verdict row: *"status-surface logic must key off `status` (`idle`/`busy`), never assume `state` is
> only `working`/`done`."*

**The keeper inspects neither.** Recording the two new rows is a doc change I did not make — this lane
does not edit `docs/specs/**` (§12) and both need a receipt block re-run by `tools/verify_receipts.py`.

---

## 11. WHERE THIS BRIEF WAS WRONG

Ordered by how much it would have cost a reader who trusted it.

1. **"is there anything in the roster that actually distinguishes a live body from a dead one? If
   there is, the roster arm can be repaired rather than dropped, and reading A gets much cheaper."**
   The premise is right and **the conclusion does not follow**. MEASURED (§3): `pid`/`status` presence
   is a perfect live/dead discriminator, **and repairing the arm that way changes nothing about this
   outage**, because efa0 was alive throughout. The brief frames an *idleness* failure as a *liveness*
   failure. The useful cut is `status == "busy"`, not `status` present.
2. **"At ~04:05Z the session process finally exited"** — right, and the framing around it
   (*"Daemon idle-exit is the candidate"*, *"If entries are removed on a timer, the keeper's blindness
   has a bounded duration"*) is right in mechanism and **wrong in reassurance**. MEASURED (§4): the
   timer is real and it is 8h, but it only un-blinds the keeper for `settled` retirements. **2 of 3
   retired supervisors on this host retired `idle-prompt` and are `blocked` in the keeper's list right
   now — for those, the blindness has no bound at all.**
3. **"My own probe … showed keys […] and NO `state` key at all. The interface saw `state`. One of us is
   reading a different surface."** Neither was. MEASURED (§1a): rows are heterogeneous by `kind` and
   the probe's key list is exactly one interactive row's. **The interface's read-only report was
   correct in full** — dead and retired bodies stay listed with `status: null, state: "blocked"`,
   whereas a live body reads `status: busy`. It was also *incomplete* in the way that matters: a live
   **idle** body reads `status: "idle"`, and that third value is the whole answer.
4. **"Nothing in `state/events.jsonl` explains it."** True as stated, and it points away from the file
   that does. MEASURED (§4): `~/.claude/daemon.log` logs the retirement verbatim, with reason and
   threshold. `state/events.jsonl` does contain an efa0 line in the window (`status_changed
   working→idle`, 04:14:50Z) — **14 seconds after the page**, so it is a consequence, not a cause.
5. **"the keeper timer … ticked roughly every 16 minutes"** — MEASURED correct (`OnUnitActiveSec=15min`
   plus ~1.1s of run time and systemd accuracy). No correction; recorded because I checked it.
6. **The `--all`-vs-plain caution (#1) was excellent and I obeyed it.** Every count in this report names
   its spelling. Recorded so the next brief keeps it.

---

## 12. EVERY COMMAND THAT TOUCHED A FLEET HOME

| verb | home | write? |
|---|---|---|
| `fleet.status_snapshot()` (imported, not the CLI) | `/home/altai/proga/fleet` (live) | **read-only** |
| `python3 bin/fleet.py home` | isolated `$TMPDIR/w61/home` | read-only |
| `python3 bin/fleet.py init` | isolated `$TMPDIR/w61/home` | wrote that home's `state/worker-settings.json` |
| `python3 bin/fleet.py spawn w61probe --model haiku` | isolated `$TMPDIR/w61/home` | that home's registry only |
| `python3 bin/fleet.py kill w61probe` | isolated `$TMPDIR/w61/home` | that home's registry only |
| `claude agents --json` / `--json --all` | n/a | read-only, ~40 invocations |

**Never run:** `fleet_keeper.py` in any form (including `--dry-run`), any `fleet` verb against the live
home, anything that takes `fleet.lock`. **Never written:** `state/keeper/last-page.json`, the claim,
`supervisor/**`, the live registry, `state/events.jsonl`. **No page was sent.** The `w61probe` haiku
session was killed (`state: "stopped"`, §3); it is the only row I added to the machine-wide roster and
it is terminal.

**Artefacts** (outside the repo, `$CLAUDE_JOB_DIR/tmp/w61/`): `plain.json`, `all.json`,
`roster-samples.jsonl` (38 samples), `rule-audit.txt`, `drive_rules.py`, `sample.py`, and the three
suite logs `base-312.txt` / `lane-312.txt` / `lane-310.txt`. The sampler (a read-only 45 s
`claude agents --json` poller, PID 304534) was **stopped at 04:58Z**; nothing of mine is still running.

---

## 13. SUITE FLOOR

**Prediction, written before the run** (`state/journals/w61-keeperblind.md`, 04:45Z): no movement —
`4946 collected, 6 failed, 4923 passed, 16 skipped, 1 xfailed`, identical on 3.10 and 3.12. Reason: the
only tracked change on this branch is this file, and `docs/lanes/` is a member of
`tests/test_doc_claims.py:447 _HISTORICAL_PREFIXES`, exempt by path prefix — an exemption itself pinned
at `tests/test_doc_claims.py:761-763`. No test enumerates `docs/lanes/` contents.

**MEASURED. Prediction held exactly, three runs, each from its own `git clone --no-local` — never
from the tree being edited.**

| tree | commit | interpreter | result |
|---|---|---|---|
| `clone A` | `036b21f` (baseline) | 3.12 | `6 failed, 4923 passed, 16 skipped, 1 xfailed in 313.84s` |
| `clone B` | `60f73e6` (this lane) | 3.12 | `6 failed, 4923 passed, 16 skipped, 1 xfailed in 321.09s` |
| `clone B` | `60f73e6` (this lane) | 3.10 | `6 failed, 4923 passed, 16 skipped, 1 xfailed in 359.81s` |

**4946 collected in all three. The floor did not move, and the baseline I took from a clean clone
reproduces the brief's stated `036b21f` baseline exactly.** The six failures are the same six ids in
all three runs, and they are this host's assumptions, not fleet defects — four drive-qualified-path
escapes (`test_fleet_index::TestPathContainment` ×3, `test_fleet_q::TestOutlinePathContainment` ×1)
and two venv-shim re-execs (`test_terminal_surface::TestCollaboratorInstall` ×2).

Command, verbatim: `uv run --no-project --python 3.1x --with pytest python -m pytest -q`, with `HOME`
pinned to the operator's real home (w60's `$HOME`-redirect fixture, `tests/conftest.py:115`).
