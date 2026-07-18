# claude 2.1.212 contract re-verification — transient daemon lifecycle

**Author:** fleet worker `md-contract` (M-D wave), 2026-07-17
**Machine:** Windows 10 Pro 19045, `claude 2.1.212`, `C:/Users/Techn/.local/bin/claude`
**Status:** `[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]` — no verdict in
`docs/specs/native-substrate.md` is self-ratified by this document.

Every receipt below is a command this worker actually ran, pasted verbatim —
**with one class of exception, called out explicitly wherever it appears: the
dead-daemon receipts (§Q2, §Q3's transient row) are MANAGER REPORTS this worker
could not reach and did not reproduce.** Two independent waves have now failed
to reach that state; see §Q2 and the fix-wave disposition below.

Probe harness: `probe.py` / `probe_b.py` / `probe_c.py` (throwaway temp project
dirs, `fleet|md-probe|` name prefix, every dispatched sid stopped+rm'd at exit;
never `claude daemon stop`, never a sid this worker did not dispatch, apart from
the brief's pre-authorized pin debris).

**Revision 2 (2026-07-17)** — corrected under adversarial review
(`MD-CONTRACT-REVIEW-2026-07-17.md`): the §Q4 grep receipt was incomplete (M2),
the shutdown counts were wrong (M3 — 15/15 and 4/4, not 16/16 and 3/3), and the
transient message's provenance was overstated (M4). Every correction is marked
inline where it applies; the verdicts are unaffected.

---

## Headline: the brief's central premise does not reproduce

The task brief states, as manager-verified evidence:

> With daemon LIVE: `claude rm` "settles (killed)" the session (daemon log) but
> the sid REMAINS in `claude agents --json --all` — pin `test_5_pin_archive_rm`
> asserts roster-gone and fails.

**This is REFUTED at 2.1.212, 3/3 samples** (§Q1). With a live daemon, `claude rm`
removes the roster entry *and* its backing `~/.claude/jobs/<short>/` dir within
<1s — against a settled session *and* against a live, mid-turn one.

**The pin suite passes 6/6 unmodified on this machine** (§Q1.4). The RED the
manager observed is real but is **daemon-lifecycle-dependent, not a contract
break**: `claude rm` fails only in the dead-daemon window, and whether that
window exists during a pin run depends on whether *any* `--bg` session is alive
to hold the transient daemon open.

Because the premise did not survive re-verification, Part 2 is built against the
mechanism this document establishes — a **failure-message taxonomy** (§Q3) —
not against "rm leaves a tombstone".

---

## The lifecycle rule that explains everything

`claude daemon status`, taken while this worker's own probes were running:

```
$ claude daemon status
pid:     35728
version: 2.1.212
uptime:  270s
origin:  transient — started on-demand by `claude --bg` (pid 38708) in C:\proga\fleet-md-contract
config:  C:\Users\Techn\.claude\daemon.json
log:     C:\Users\Techn\.claude\daemon.log

bg sessions:
  sock dir:     \\.\pipe\cc-daemon-*
  control.sock: reachable
  bg workers:   5 running (control.sock), 5 in roster.json
  roster.json:  updated 14s ago

holding this daemon open:
  5 bg workers running (daemon waits for them to settle)

to let it idle-exit: wait for (or cancel) bg workers and close any `claude agents`
```

`claude daemon --help` @2.1.212:

```
  Service install is disabled in this version — the daemon runs on demand
  and exits when the last client disconnects.
```

**The daemon idle-exits only when it has zero live workers AND zero clients.**
A live `--bg` session holds it open; so does an open `claude agents`.

### Observability consequence (binding on this whole report)

**This worker is itself a `--bg` session** (`5af0f6aa`, visible in
`roster.json` → `workers`), as are its M-D sibling workers. Therefore the daemon
**cannot** die while this worker runs. Every probe below executed against a
permanently-live daemon. This is not a limitation to work around — it is itself
a load-bearing finding (§Q2), and it explains why the manager (probing from an
interactive session with no live bg workers) and this worker (a bg worker) see
different behavior from identical commands.

---

## Q1 — rm with a LIVE daemon: does the sid ever leave `--all`?

**Answer: it leaves immediately — from `--all`, from the default listing, and
from disk. 3/3 samples. The brief's premise is REFUTED.**

### Q1.1 — settled/`done` session (pre-authorized pin debris `0a208ce0`)

```
### BEFORE rm 0a208ce0
  --all  : {"id": "0a208ce0", "cwd": "...\\fleet-pin-proj-6zjbq26e", "kind": "background",
            "startedAt": 1784251169965, "sessionId": "0a208ce0-6b76-41c1-85e6-751c85306d13",
            "name": "fleet|pin-w1|Reply with exactly: PIN-OK", "state": "done"}
  default: ABSENT
  jobsdir: PRESENT
### rm
removed 0a208ce0
rc=0
### AFTER +0s
  --all  : ABSENT
  default: ABSENT
  jobsdir: GONE
### AFTER +5s
  --all  : ABSENT
  default: ABSENT
  jobsdir: GONE
```

### Q1.2 — LIVE, mid-turn session (`probe_b.py`, own dispatch `89dc2371`)

G12 recorded rm-against-a-live-session as "UNOBSERVED and out of contract". It is
now observed: **rm does not refuse, does not require a prior stop — it removes.**

```
=== T+12s: worker should be MID-TURN (live) ===
  [before rm]
    --all   : {"pid": 28604, "id": "89dc2371", ..., "name": "fleet|md-probe|b-live",
               "status": "busy", "state": "working"}
    jobsdir : PRESENT
=== rm against the LIVE session ===
  rc=0
  stdout: removed 89dc2371
  stderr:
  [after rm +0s]
    --all   : None          <- ABSENT
    default : None
    jobsdir : GONE
  [after rm +5s]  --all: None   jobsdir: GONE
  [after rm +15s] --all: None   jobsdir: GONE
  [after rm +30s] --all: None   jobsdir: GONE
  [after rm +60s] --all: None   jobsdir: GONE
```

### Q1.3 — the exact pin-test-5 sequence: stop → poll → rm (`probe_c.py`, `d52fdf0a`)

```
=== claude stop (live, mid-turn) ===
  rc=0 stdout='stopped d52fdf0a' stderr=''

=== poll roster after stop (pin's _wait_for_roster_gone_or_dead window) ===
  +1.5s: status=None state='stopped' pid=None -> fleet-live=False
  -> reached gone-or-dead (archive gate 3 would now allow rm)

=== rm after stop ===
  rc=0 stdout='removed d52fdf0a' stderr=''
  [after rm]
    --all   : None
    default : None
    jobsdir : GONE
```

`claude stop` on a live session drops the entry to a `state`-only `stopped`
record (fleet's gone-or-dead gate satisfied) in **1.5s**, and the follow-up rm is
clean. The pin's 60s `_wait_for_roster_gone_or_dead` window is ~40x the observed
need.

### Q1.4 — the pin suite itself, unmodified, on 2.1.212

```
$ FLEET_LIVE=1 PYTHONIOENCODING=utf-8 py -3.13 -m pytest tests/integration/test_native_pin.py -v
tests/integration/test_native_pin.py::test_1_pin_dispatch_and_roster_contract PASSED [ 16%]
tests/integration/test_native_pin.py::test_2_pin_stop_hook_outcome PASSED             [ 33%]
tests/integration/test_native_pin.py::test_3_pin_fork_steer PASSED                    [ 50%]
tests/integration/test_native_pin.py::test_4_pin_stop_no_hook_tombstone PASSED        [ 66%]
tests/integration/test_native_pin.py::test_5_pin_archive_rm PASSED                    [ 83%]
tests/integration/test_native_pin.py::test_6_pin_record_pass PASSED                   [100%]
======================== 6 passed in 83.76s (0:01:23) =========================
```

`daemon.log` across that whole run — **no shutdown line at all**; the daemon this
worker holds open never idle-exited, so no rm ever met a dead daemon:

```
$ sed -n '567,$p' ~/.claude/daemon.log | grep -E "shutting down|daemon start|settled|spawned"
[2026-07-17T01:36:08.452Z] [bg] bg spawned 037bac43 (shell)
[2026-07-17T01:36:30.164Z] [bg] bg spawned a259209b (shell)
[2026-07-17T01:36:50.955Z] [bg] bg spawned e4955de9 (shell)
[2026-07-17T01:37:00.962Z] [bg] bg settled e4955de9 (killed)
[2026-07-17T01:37:01.971Z] [bg] bg settled a259209b (killed)
[2026-07-17T01:37:04.417Z] [bg] bg settled 037bac43 (killed)
```

**Interpretation.** The pin tier is not measuring only the native contract — it is
also measuring, invisibly, whether a bg session happened to be holding the daemon
open. That confound is the pin's real defect at 2.1.212, and §Part-2 fixes it by
making the suite *record and report* daemon liveness instead of silently
depending on it.

---

## Q2 — rm/stop with a DEAD daemon; is there a sanctioned revival verb?

**Answer: BLOCKED (containment), by design of the brief — with the reasoning the
brief asked for, plus a mechanism finding that supersedes the question.**

The dead-daemon state is **unreachable from this worker**. The only two ways to
reach it are:

1. `claude daemon stop [--any]` — **explicitly banned** by the brief's
   containment ("terminates background sessions machine-wide, including sessions
   that are not yours"). Three sibling M-D workers were live throughout.
2. Ending every `--bg` session on the machine — this worker *is* one, and the
   others are not this worker's to end. Self-termination also ends the probe.

Per the brief's instruction ("If a probe seems to need it, write BLOCKED with the
reasoning instead"), Q2's dead-daemon half is **not probed**. The manager's own
receipts for it stand unchallenged: nothing this worker observed contradicts
them, because no probe here reached that state.

### `claude daemon run` detached — NOT ATTEMPTED, with reasoning

The brief allows this as a possible revival nudge. This worker refuses it on
containment grounds: starting a second supervisor while 5 bg workers (this one
plus 3 M-D siblings plus a probe) are live risks a **takeover/adopt**, which
`daemon.log` shows is a real, worker-affecting code path:

```
[2026-07-17T00:35:29.135Z] [bg] bg adopt: adopted=1 respawned=0 dead=0
[2026-07-17T00:35:44.160Z] [bg] bg: post-takeover prewarm burst — respawned 0/1 stale workers, 1 refused in 0s
```

A takeover that respawns or refuses a sibling worker is exactly the machine-wide
blast radius the containment section exists to prevent. **Recommend the operator
run this probe standalone**, on a quiet machine, alongside the G9 probe that
`native-substrate.md` already parks for the same reason.

### The finding that supersedes the question

Fleet does not need a revival verb, because **fleet's own dispatch already is
one** and its hygiene paths must not dispatch (a dispatch mints a *new billable
session*; using one as a side effect of `fleet archive` would be a contract
violation, not a nudge). The correct adaptation is therefore the brief's second
option — **loud-but-nonfatal skip, husk stays, next pass retries** — and it is
what Part 2 implements.

**Where this actually bites (the real-world case, argued from the lifecycle
rule):** `fleet archive` and `fleet autoclean` are *by construction* run when
workers are NOT live — archive only ever targets terminal-state workers idle past
a TTL, and the autoclean scheduled task fires on a timer with no bg session
necessarily alive. That is precisely the zero-live-worker, zero-client state in
which the daemon has idle-exited. **Fleet's hygiene tier is the one code path
most likely to meet a dead daemon, and least able to revive it.** This is why the
Part-2 fix is not cosmetic.

---

## Q3 — the failure-message taxonomy (the actual contract change)

**`claude rm` is NOT idempotent — G12's idempotency assumption is REFUTED.**

`native-substrate.md` G12 records "idempotency against an already-removed id" as
UNOBSERVED, and `bin/fleet.py`'s own teardown docstring asserts "`claude rm` is
idempotent on an already-gone id (contract G12)". Observed:

```
=== rm a never-existed id ===
No job matching 'deadbeef'
rc=1

=== rm an already-removed id (0a208ce0, rm'd earlier this session) ===
No job matching '0a208ce0'
rc=1

=== stop a never-existed id ===
No job matching 'deadbeef'. Run 'claude agents' to list running sessions.
rc=1

=== rm a FULL uuid (fleet's belt-and-braces retry path) ===
No job matching '0a208ce0-6b76-41c1-85e6-751c85306d13'
rc=1
```

So **`rc=1` from `claude rm` is three-way ambiguous**, and the message is the only
discriminator:

| stdout/stderr | rc | meaning | fleet must |
|---|---|---|---|
| `removed <id>` | 0 | removed | count as success |
| `No job matching '<id>'` | 1 | **already gone** — the desired end state | count as success (idempotent-equivalent) |
| `couldn't remove <id> — the background service may be restarting. Try again in a moment.` | 1 | **transient** — daemon dead/restarting | loud, non-fatal skip; husk stays; next pass retries |
| anything else | 1 | unknown | loud, non-fatal skip |

Pre-fix, `bin/fleet.py` collapses all three `rc=1` cases to `False` = "failed",
so an **already-clean sid is reported to the operator as `rm ... failed`** and a
**retryable dead-daemon skip is indistinguishable from a permanent one**. Both are
fixed in Part 2. The full-uuid retry in `_rm_native_session`/`_stop_native_session`
is also confirmed pointless on the already-gone path (receipt above: the full-uuid
call returns the same `No job matching`), so the classifier short-circuits it.

---

## Q4 — stale-roster hazard (G9-critical): can an idle-exit strand a `working` entry?

**Answer: NO. The idle-exit is gated on `live_workers=0` — 15/15 receipts.
Fleet's roster-based liveness verdicts cannot false-positive via idle-exit.**

> **COUNTS CORRECTED (M3, review `MD-CONTRACT-REVIEW-2026-07-17.md`).** This
> section previously said **16/16** idle-exit and **3/3** upgrade. Both were
> miscounts of the very block pasted below: the truth is **15/15** idle-exit
> and **4/4** upgrade. The errors compounded in the worst direction —
> overstating the reassuring sample and *understating the hazard* sample. The
> unaccounted 4th upgrade is line 515, which is the very shutdown whose
> `1 refused` aftermath this document twice cites as the residual G9 hazard:
> the denominator excluded an event while the prose cited its consequence.
> **The verdict is unaffected** (15/15 is still no counter-example; 4/4 upgrade
> shutdowns still carry live workers) — only the arithmetic was wrong. The
> count commands are now receipts in their own right, so the next reader
> re-derives instead of counting 19 lines by eye:

```
$ grep -c "shutting down (cause=idle_exit" ~/.claude/daemon.log
15
$ grep "shutting down (cause=idle_exit" ~/.claude/daemon.log | grep -c "live_workers=0"
15
$ grep -c "shutting down (cause=upgrade" ~/.claude/daemon.log
4
$ grep "shutting down (cause=upgrade" ~/.claude/daemon.log | grep -o "live_workers=[0-9]*"
live_workers=1
live_workers=1
live_workers=4
live_workers=1
$ grep -c "shutting down" ~/.claude/daemon.log
19
$ grep -c "daemon start" ~/.claude/daemon.log
25
```

Every `shutting down` line in the entire `~/.claude/daemon.log` history
(2026-07-07 → 2026-07-17, 25 daemon starts):

```
$ grep -n "shutting down" ~/.claude/daemon.log
17:  [2026-07-07T18:08:22.141Z] shutting down (cause=idle_exit, uptime=17656s, leases=0, live_workers=0)
28:  [2026-07-09T15:16:58.096Z] shutting down (cause=idle_exit, uptime=5587s,  leases=0, live_workers=0)
43:  [2026-07-13T17:43:16.208Z] shutting down (cause=idle_exit, uptime=10568s, leases=0, live_workers=0)
52:  [2026-07-13T20:49:22.869Z] shutting down (cause=idle_exit, uptime=52s,    leases=0, live_workers=0)
61:  [2026-07-13T21:00:21.999Z] shutting down (cause=idle_exit, uptime=156s,   leases=0, live_workers=0)
79:  [2026-07-13T21:31:57.874Z] shutting down (cause=idle_exit, uptime=1326s,  leases=0, live_workers=0)
88:  [2026-07-13T21:33:24.926Z] shutting down (cause=idle_exit, uptime=7s,     leases=0, live_workers=0)
102: [2026-07-13T21:37:10.282Z] shutting down (cause=idle_exit, uptime=219s,   leases=0, live_workers=0)
111: [2026-07-13T23:33:00.016Z] shutting down (cause=idle_exit, uptime=5407s,  leases=0, live_workers=0)
147: [2026-07-14T01:15:04.986Z] shutting down (cause=upgrade,   uptime=5222s,  leases=2, live_workers=1)
165: [2026-07-14T06:49:09.923Z] shutting down (cause=upgrade,   uptime=20044s, leases=2, live_workers=1)
186: [2026-07-15T12:55:13.419Z] shutting down (cause=idle_exit, uptime=306s,   leases=0, live_workers=0)
202: [2026-07-15T19:45:00.639Z] shutting down (cause=idle_exit, uptime=11528s, leases=0, live_workers=0)
223: [2026-07-15T23:13:19.255Z] shutting down (cause=upgrade,   uptime=11402s, leases=0, live_workers=4)
332: [2026-07-16T02:26:28.142Z] shutting down (cause=idle_exit, uptime=11588s, leases=0, live_workers=0)
515: [2026-07-17T00:35:25.950Z] shutting down (cause=upgrade,   uptime=37086s, leases=2, live_workers=1)
527: [2026-07-17T01:10:44.011Z] shutting down (cause=idle_exit, uptime=2117s,  leases=0, live_workers=0)
540: [2026-07-17T01:18:18.785Z] shutting down (cause=idle_exit, uptime=221s,   leases=0, live_workers=0)
553: [2026-07-17T01:20:17.734Z] shutting down (cause=idle_exit, uptime=47s,    leases=0, live_workers=0)
```

- **`cause=idle_exit`: 15/15 have `live_workers=0` and `leases=0`.** No
  counter-example exists in 10 days of history. The daemon *waits for workers to
  settle* — its own status text says so verbatim ("daemon waits for them to
  settle"), and the settle-then-exit ordering is visible with 5s spacing:
  ```
  [01:18:07.488Z] bg settled 9ba5b78b (killed)
  [01:18:11.996Z] bg settled b3ae3a5d (killed)
  [01:18:13.775Z] bg settled 65dcf3e7 (killed)
  [01:18:18.785Z] idle 5s with no clients — exiting
  [01:18:18.785Z] shutting down (cause=idle_exit, uptime=221s, leases=0, live_workers=0)
  ```
- **`cause=upgrade`: 4/4 shut down WITH live workers** (`live_workers=1`, `1`,
  `4`, `1` — lines 147, 165, 223, 515). This — not idle-exit — is the residual
  stale-roster vector, and it is immediately followed by adopt/respawn by the
  successor daemon. The 4th (line 515, `live_workers=1`) is the one this
  document's prose originally dropped from the count while quoting its
  aftermath as the finding:
  ```
  [2026-07-17T00:35:29.135Z] bg adopt: adopted=1 respawned=0 dead=0
  [2026-07-17T00:35:44.160Z] bg: post-takeover prewarm burst — respawned 0/1 stale workers, 1 refused in 0s
  ```
  The `1 refused` is the ambiguous case (a worker neither adopted nor respawned).

**Structural corroboration.** `~/.claude/daemon/roster.json` holds only *live*
workers (`workers` dict, keyed by short id, each with a `pid`), while
`claude agents --json --all` is backed by the `~/.claude/jobs/<short>/` dirs
(38 dirs ↔ 39 `--all` entries at sample time). `status`/`pid` — the two keys
fleet's liveness test reads — appear only for entries the `workers` dict vouches
for. An idle-exit at `live_workers=0` therefore leaves a roster with **no**
status/pid-bearing entries: it cannot manufacture a phantom `working`.

**Verdict for fleet: no roster read needs to change.** The G9 epoch-freeze
doctrine already covers the only real ambiguity (upgrade-shutdown + refused
respawn), and G9's own rule — "never assume dead on ambiguity" — is the correct
handling. Fixing anything here would be building against a hazard the evidence
does not show.

### Roster-read call-site audit (grep receipt, per brief)

> **CORRECTED (M2, review `MD-CONTRACT-REVIEW-2026-07-17.md`).** The block
> below previously showed **14** hits and had been hand-edited, not pasted: it
> omitted `4709` — `_sweep_husks`'s own roster fetch, i.e. the hygiene tier
> *this very wave rewrote* and the one §Q2 calls "the code path most likely to
> meet a dead daemon" — and `6591` (the definition line), and it silently
> stripped the `  # noqa: E731` suffix from 6182/6858. The claim it backed
> ("a full audit of **every** read") was therefore false: 14 of 16. **The
> verdict is unchanged and survives** — the reviewer independently audited
> `4709` and reached the same "none" — but a completeness claim staged for
> operator ratification cannot rest on an incomplete receipt. Real output,
> pinned to the base ref the audit was performed at, re-run in full:

```
$ git show c1277bd:bin/fleet.py > /tmp/fleet_base.py   # base ref of this audit
$ grep -n '_fetch_agents_roster(\|"agents", "--json"' /tmp/fleet_base.py
2406:        roster_ok, payload = _fetch_agents_roster()
2746:            roster_ok, payload = _fetch_agents_roster()
2839:            roster_ok, payload = _fetch_agents_roster()
2962:    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
3699:    roster_ok, entries = _fetch_agents_roster(which=which, run=run)
3723:        roster_ok2, entries2 = _fetch_agents_roster(which=which, run=run)
3729:            roster_ok3, entries3 = _fetch_agents_roster(which=which, run=run)
4145:        roster_ok, payload = _fetch_agents_roster(which=which, run=run)
4534:        roster_ok, payload = _fetch_agents_roster(which=which, run=run)
4709:    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
5425:        result = run([exe, "agents", "--json"], capture_output=True, text=True, timeout=10)
6182:        roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731
6591:def _fetch_agents_roster(which=shutil.which, run=subprocess.run):
6600:        proc = run([exe, "agents", "--json", "--all"], capture_output=True,
6666:    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
6858:    roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731

$ grep -c '_fetch_agents_roster(\|"agents", "--json"' /tmp/fleet_base.py
16
```

Line numbers are pinned to `c1277bd`; `bin/fleet.py` has since moved (+144
lines on this branch), so re-running against `HEAD` will not reproduce them.

| call site | reader | assessed against the idle-exit timeline | change |
|---|---|---|---|
| 6591 | the `_fetch_agents_roster` definition line itself | n/a — not a read | none |
| 6600 | `_fetch_agents_roster` (the one sanctioned fetch) | uses `--all`; failure → `(False, reason)` → every caller freezes per G9 | none |
| **4709** | **`_sweep_husks`** — the hygiene tier this wave rewrote (added by M2; omitted from the original receipt) | epoch-freeze guarded: `native_epoch_suspicious(roster_ok, payload, workers)` → `raise FleetCliError("husk sweep refused: roster suspicious (G9)")`, 120 lines below the fetch. A stale roster cannot make it rm anything: it additionally skips every entry carrying `status`/`pid`, and default-deny means an unowned sid is never selected | none |
| 2406 | `cmd_status` | epoch-freeze guarded (`native_epoch_suspicious`) | none |
| 2746 / 2839 | `cmd_wait` poll + persist | epoch-freeze guarded | none |
| 2962 | `_cmd_send_native` | epoch-freeze guarded | none |
| 3699 / 3723 / 3729 | `cmd_respawn --force` | re-checks roster after a stop; treats unverified as unsafe | none |
| 4145 | dead-only autoclean tier | epoch-freeze guarded | none |
| 4534 | `cmd_archive` | epoch-freeze guarded; gate 3 skips live sids | none |
| 6182 / 6858 | spawn wedge-guard `roster_fetch` | fetch failure → `retry_safe=False` (fails safe) | none |
| 6666 | `cmd_sup_boot` | `supervisor_epoch_check` | none |
| 5425 | `_doctor_check_claude_agents` | note-only, non-`--all`; tolerates every failure by design; a dead daemon still answers from `roster.json`, so it degrades to "fewer unknown sids reported", never a false verdict | none (assessed, deliberately left) |

Every roster read is already behind the epoch-freeze or fails safe. **Zero
changes made** — per G9 doctrine and the brief's "fix only what your evidence
shows is wrong".

---

## Q5 — does an idle-exit kill still-working bg sessions?

**Answer: NO. The daemon always outlives its workers on the idle path.
`live_workers=0` gates the exit — 15/15 receipts (§Q4).**

Direct positive evidence that live workers *hold the daemon open*, from
`claude daemon status` during a probe:

```
holding this daemon open:
  5 bg workers running (daemon waits for them to settle)

to let it idle-exit: wait for (or cancel) bg workers and close any `claude agents`
```

And the ordering in the log is always settle-then-exit, never exit-then-orphan
(§Q4, 01:18:07→01:18:18 sequence). Every `bg settled <id> (killed)` in this
worker's own probe windows was caused by an explicit `claude stop`/`claude rm`
(this worker's cleanup, or the pin suite's teardown) — never by an idle-exit.

**Caveat, stated honestly:** `cause=upgrade` is a different path and *does* shut
down with live workers (4/4, up to `live_workers=4`). It is followed by adoption,
not orphaning, but "1 refused" in the post-takeover prewarm shows adoption is not
guaranteed. This is the G9-relevant residue and belongs to the operator's
standalone G9 probe, not to an idle-exit claim.

---

## Anomaly, recorded and NOT built on

`probe_b.py` sampled `--all` and the default listing ~1s apart and got
**disagreeing** views of the same live session:

```
    --all   : ... "status": "busy", "state": "working"
    default : ... "status": "idle", "state": "blocked"
```

`probe_c.py` re-probed this deliberately with 3 paired same-instant samples and
**could not reproduce it** (all 3 agreed: `status='busy' state='working'`):

```
  sample 0: --all[status='busy' state='working' pid=23588]  default[status='busy' state='working' pid=23588]
  sample 1: --all[status='busy' state='working' pid=23588]  default[status='busy' state='working' pid=23588]
  sample 2: --all[status='busy' state='working' pid=23588]  default[status='busy' state='working' pid=23588]
```

Most likely a genuine 1s-apart state transition, not a listing inconsistency.
**Unreproduced ⇒ nothing is built on it.** Recorded so a future run that sees it
again has the prior. Fleet reads `--all` everywhere that matters, so even a real
divergence here would not change a verdict.

---

## Fix-wave disposition (review `MD-CONTRACT-REVIEW-2026-07-17.md`, 2026-07-17)

Every M finding was **re-verified against my own work before acting**. The
reviewer is right on all five; **none disputed**. The two disputed receipts were
re-run and confirm against me: the §Q4 grep really does return 16 hits (I pasted
14, omitting `_sweep_husks`'s own read — the very path this wave rewrote), and
the shutdown counts really are 15/15 and 4/4 (I said 16/16 and 3/3).

| # | finding | disposition |
|---|---|---|
| **M1** | dead-daemon deferral surfaced **nowhere**; my code comment claimed the opposite | **FIXED.** `_sweep_husks` returns `(removed, deferred)`; `husks_deferred` rides the run stamp, the `autoclean_run` event and the summary line; `_doctor_check_autoclean` reports a starved tier. Deliberately **not** pushed into `errors` (rc stays 0) — a transient daemon is routine, and reddening it is the cry-wolf this branch exists to kill. Injection F now goes RED, plus 3 new injections (stamp field, doctor branch, gloss). |
| **M2** | §Q4 grep receipt hand-edited: 14 of 16 hits, `_sweep_husks` omitted | **FIXED.** Real 16-line output re-pasted, pinned to base ref `c1277bd`, `# noqa` suffixes intact; `4709` and `6591` added to the audit table. Verdict unchanged (`4709` is epoch-guarded at `:4829`) — but a completeness claim staged for ratification cannot rest on an incomplete receipt. |
| **M3** | `16/16`/`3/3` miscounted my own pasted block; copied into the spec twice | **FIXED.** → `15/15` and `4/4` (`live_workers=1,1,4,1`) in both documents; the count commands are now receipts so the next reader re-derives instead of counting by eye. The 4th upgrade (line 515) is the one whose `1 refused` aftermath I quote as the hazard — I had excluded it from the denominator while citing its consequence. |
| **M4** | `RM_TRANSIENT` labelled "copied VERBATIM from the live probes"; it is a manager report | **FIXED.** Relabelled `[OBSERVED interactive 2026-07-17 manager session — NOT RE-OBSERVED]` at every copy (test stub, `bin/fleet.py` comment, G12 row). The match was **already** normalized to the dash-free middle phrase — that is now stated as deliberate and pinned by `test_transient_matches_regardless_of_dash_style`. Fail-safe-on-unknown-message promoted from accident-of-structure to **contract** (`TestUnknownMessageShapeFailsSafe`). Capture added to the operator's open list. |
| **M5** | commit said `rm/stop`; `stop` unclassified; spec's justification false at 2 of 5 call sites | **FIXED — reviewer's preferred option, and here is why.** I took the preferred route (classify `stop`) rather than the minimum (retract the spec claim): the defect is not cosmetic. `fleet kill` on an already-gone sid exited **1**, told the operator to investigate a session that is verifiably gone, and — the part that decided it — wrote **`interrupt_outcome=False` into the durable event log**, a wrong datum every future consumer inherits. A console message can be re-read; a bad event cannot. The rm half of the same contract already reported `gone`; leaving the two halves disagreeing about one fact was untenable. The false spec sentence is corrected too, naming the two call sites that never re-checked. |
| m1 | `gone` short-circuit is the one fail-**unsafe** direction | **FIXED** as named: both hygiene call sites pass the roster entry's own `id`; `_native_job_ref` stays the fallback. `test_gone_short_circuits_the_full_sid_retry` keeps its meaning (the short-circuit remains) and gains a sibling pinning rm-by-roster-id. |
| m2 | pin's `_daemon_alive()` samples the confound, racy both ways | **FIXED** as named: test 5 branches on fleet's own `deferred (daemon-transient)` classification (race-free — it *is* the rm); `_daemon_alive()` retained for the diagnostic paste and as fallback. The rm-taxonomy probe now keys off its own output too. |
| m3 | G12's action column contradicts its own amendment | **FIXED**: the two superseded items struck through and tagged; the third (transcript clearing) left standing — it is still genuinely UNOBSERVED. No verdict touched. |
| m4 | `..._still_archives` never asserted the archive | **FIXED**: asserts `dest` has content. |
| m5 | docstring cites §Q3 for a claim §Q3 does not make | **FIXED**: split — the full-uuid half is a receipt, the transient short-circuit is labelled **reasoning, not a receipt**. |
| N1 | spurious `rc=1`→`rc=0` in the stop summary | **FIXED.** |
| N2 | ASCII hyphen vs em-dash across three transcriptions | **FIXED**: em-dash everywhere, with a note that the dash is a transcription choice, not evidence — which is precisely why the regex spans neither side of it. |
| N3 | `no-claude`/`error` glosses unpinned (Injection G stayed green) | **FIXED**: `TestRmOutcomeNotes` pins all four; Injection G now goes RED. |

**Nothing disputed.** The reviewer's `SPURIOUS-FIX: none` verdict and its
doctrine checks are recorded as-is; no counter-argument is offered because none
survived checking.

## Fix-wave 2 disposition (re-review, 2026-07-17) — the twins wave 1 missed

The re-review found all 13 wave-1 findings fixed, and three **new** defects that
wave 1 *introduced or left half-done*. All three re-verified here before acting;
**none disputed**.

| # | finding | disposition |
|---|---|---|
| **ND-1** | **MAJOR.** `m1` hardened both `rm` call sites and **neither `stop` site** — in the same commit that gave `stop` the `gone`→success inference `m1` exists to make safe. | **FIXED + REPRO'D MYSELF FIRST.** My repro, against `e2ee7c5`: with a CLI answering only to its own short id, `fleet kill` used ref `['aaaabbbb']` (derived), got `No job matching` → `gone` → **rc=0, `w1: killed`, `interrupt_outcome=True`, status=dead — while the session ran on**. Fleet would then forget a live bg session that every husk sweep skips forever (status/pid-live): the rogue-session class `_cleanup_wedged` calls a C1 CRITICAL, reached through the front door. The reviewer's severity argument is exactly right and worth restating: **the pre-M5 code was fail-SAFE on this input** (rc=1, "investigate manually"), so my wave-1 "cry-wolf fix" removed the only signal that would have caught the true case. `_cmd_kill_native` now passes `ref=rec.get("native_short_id")`; re-running the repro shows ref `['zz9qk7xd']` and the session really stopped. Pinned by `test_kill_stops_by_the_captured_short_id_not_a_derived_ref` (red on revert, verified). Retired sids keep the derived fallback — they have no captured id, which is what `_native_job_ref` is for. **The reviewer's caveat is accepted and recorded, not papered over:** `native_short_id` is itself derived on 2 of its 6 write paths (the fast-sid paths), so this is a strict improvement on 4 paths and a no-op on 2 — *not a cure*. `_native_job_ref`'s docstring, which argued against this fix, is marked stale with the reason. |
| **ND-2** | MINOR. The pin's `_daemon_alive()` fallback was **documented but never implemented** — `alive` appeared in no branch condition. | **FIXED as named.** This was M1's defect in miniature — a comment asserting what the code does not do — and mine. It bites because `rm_deferred` can only be True if `_NATIVE_CLI_TRANSIENT_RE` matched, and that regex rests on a string **two waves failed to observe** (M4): under any other real message, fleet correctly says `deferred (failed)` and test 5 would hard-assert "a genuine contract regression" on a machine whose daemon is merely down — the exact false-RED `m2` existed to kill. Fleet's classification stays primary; `_daemon_alive()` now corroborates the unclassified shape (`rm_unclassified and alive is False`). The pin still fails on vendor drift: a leftover sid with no deferral line, or a live/unknown daemon, hard-asserts. The reviewer's coupling point is also fixed: `NATIVE_RM_DEFERRED_PREFIX` is now a constant both sides import, pinned by `TestDeferralLineFormat` (red when renamed). **Bonus:** if the unclassified branch ever fires, the skip message tells the operator to capture the stderr — it is the receipt two waves could not get. |
| **ND-3** | MINOR. The doctor note fired on the **first** deferral — the normal case per my own §Q2 — so starvation rendered like Tuesday. | **FIXED as named.** My M1 note even conceded the gap ("if this count persists across runs") while reading from a stamp that holds one pass and cannot show persistence. The streak now comes from `events.jsonl` (append-only, and carrying `husks_deferred` since M1): `_autoclean_deferral_streak()` counts consecutive deferring runs backwards from newest, resetting on any pass that removed a husk (proof the daemon was reachable). Doctor notes only at `AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD` (3 — the scheduled task's floor is hourly, so ≥3h of unreachability) and prints the streak and its start. Still note-only (`ok=True`). The wave-1 test that pinned first-deferral firing was itself pinning the defect and is updated with the reason. |
| n1 | the corrected §Q4 receipt was *still* hand-edited (line 6858 indented 8, file has 4) | **FIXED**, and verified mechanically this time rather than by eye: all 16 lines diffed byte-for-byte against `git show c1277bd:bin/fleet.py | grep -n …`, 0 mismatches. |

**Standing lesson, recorded for the next wave.** Both ND-1 and ND-2 are the same
error class: *a fix applied at one call site and not its twin, or promised in a
comment and not in the code.* Wave 1 fixed `rm` and forgot `stop`; wave 1 wrote
the fallback comment and no fallback. When this branch adds a `ref=`-style
parameter or a documented fallback, grep every call site and assert the comment
against the code before claiming the finding closed.

---

## Summary of contract deltas for `docs/specs/native-substrate.md`

All tagged `[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]`; none self-ratified.

1. **Daemon lifecycle (new row).** Transient, on-demand, no service install.
   Idle-exits 5s after the last client disconnects **and** `live_workers` reaches
   0. A live `--bg` session or an open `claude agents` holds it open.
2. **G12 (rm) — idempotency REFUTED.** Already-gone id ⇒ `rc=1`,
   `No job matching '<id>'`. The message, not the exit code, is the discriminator.
3. **G12 (rm) — live-session behavior OBSERVED** (was "UNOBSERVED and out of
   contract"): rm against a live session removes it; no refusal, no stop required.
4. **G12 (rm) — dead-daemon failure mode** (manager receipt, unchallenged): `rc=1`,
   `couldn't remove <id> — the background service may be restarting.` rm does not
   revive the daemon; only a dispatch does.
5. **Stop.** On a live session: `rc=0` `stopped <id>`, roster drops to a
   `state`-only `stopped` record in ~1.5s. On a gone id: `rc=1`,
   `No job matching '<id>'. Run 'claude agents' to list running sessions.`
6. **Roster staleness (G9-relevant).** Idle-exit cannot strand a live-looking
   entry (`live_workers=0` gate, 15/15). `cause=upgrade` can (4/4) and is followed
   by adopt/respawn with an observed "1 refused" ambiguity.
7. **Pin-tier confound.** Pin outcomes depend on whether a bg session holds the
   daemon open. The suite must record daemon liveness rather than silently
   inherit it.
