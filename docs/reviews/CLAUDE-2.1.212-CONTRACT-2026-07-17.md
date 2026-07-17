# claude 2.1.212 contract re-verification — transient daemon lifecycle

**Author:** fleet worker `md-contract` (M-D wave), 2026-07-17
**Machine:** Windows 10 Pro 19045, `claude 2.1.212`, `C:/Users/Techn/.local/bin/claude`
**Status:** `[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]` — no verdict in
`docs/specs/native-substrate.md` is self-ratified by this document.

Every receipt below is a command this worker actually ran, pasted verbatim.
Probe harness: `probe.py` / `probe_b.py` / `probe_c.py` (throwaway temp project
dirs, `fleet|md-probe|` name prefix, every dispatched sid stopped+rm'd at exit;
never `claude daemon stop`, never a sid this worker did not dispatch, apart from
the brief's pre-authorized pin debris).

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

**Answer: NO. The idle-exit is gated on `live_workers=0` — 16/16 receipts.
Fleet's roster-based liveness verdicts cannot false-positive via idle-exit.**

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

- **`cause=idle_exit`: 16/16 have `live_workers=0` and `leases=0`.** No
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
- **`cause=upgrade`: 3/3 shut down WITH live workers** (`live_workers=1`, `1`, and
  `4`). This — not idle-exit — is the residual stale-roster vector, and it is
  immediately followed by adopt/respawn by the successor daemon:
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

```
$ grep -n '_fetch_agents_roster(\|"agents", "--json"' bin/fleet.py
2406:        roster_ok, payload = _fetch_agents_roster()
2746:            roster_ok, payload = _fetch_agents_roster()
2839:            roster_ok, payload = _fetch_agents_roster()
2962:    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
3699:    roster_ok, entries = _fetch_agents_roster(which=which, run=run)
3723:        roster_ok2, entries2 = _fetch_agents_roster(which=which, run=run)
3729:            roster_ok3, entries3 = _fetch_agents_roster(which=which, run=run)
4145:        roster_ok, payload = _fetch_agents_roster(which=which, run=run)
4534:        roster_ok, payload = _fetch_agents_roster(which=which, run=run)
5425:        result = run([exe, "agents", "--json"], capture_output=True, text=True, timeout=10)
6182:        roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)
6600:        proc = run([exe, "agents", "--json", "--all"], capture_output=True,
6666:    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
6858:        roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)
```

| call site | reader | assessed against the idle-exit timeline | change |
|---|---|---|---|
| 6600 | `_fetch_agents_roster` (the one sanctioned fetch) | uses `--all`; failure → `(False, reason)` → every caller freezes per G9 | none |
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
`live_workers=0` gates the exit — 16/16 receipts (§Q4).**

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
down with live workers (3/3, up to `live_workers=4`). It is followed by adoption,
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
5. **Stop.** On a live session: `rc=1`→`rc=0` `stopped <id>`, roster drops to a
   `state`-only `stopped` record in ~1.5s. On a gone id: `rc=1`,
   `No job matching '<id>'. Run 'claude agents' to list running sessions.`
6. **Roster staleness (G9-relevant).** Idle-exit cannot strand a live-looking
   entry (`live_workers=0` gate, 16/16). `cause=upgrade` can (3/3) and is followed
   by adopt/respawn with an observed "1 refused" ambiguity.
7. **Pin-tier confound.** Pin outcomes depend on whether a bg session holds the
   daemon open. The suite must record daemon liveness rather than silently
   inherit it.
