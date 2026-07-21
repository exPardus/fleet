# ME-DAEMON-REVIEW — hostile review of `me/daemon`

**Reviewer:** fleet worker `me-daemon-review`, worktree `C:/proga/fleet-me-daemon-review`,
branch `me/daemon-review` (merge `4bb9b54` = `fleet-impl@4cc8373` + `me/daemon@1015344`).
**Date:** 2026-07-21.
**Under review:** `d97f6de`, `89d1928`, `957a4f8`, `1015344` on base `ac3e34d` (+715/−10).
**Baseline in this worktree:** `1170 passed, 6 skipped` (`py -3.13 -m pytest -q`), matching the
manager's number. Not re-litigated.

**Probe context (containment clause v1.7).** This reviewer is a `--bg` session — confirmed
directly from the substrate under review: `~/.claude/daemon.log:722` reads
`[2026-07-21T15:54:40.276Z] [bg] bg spawned 2dbed67b (shell)`, and `2dbed67b` is this job. A
`--bg` session is by construction a live daemon client and **cannot reach the wedged state**.
Every finding below is therefore derived from (a) the preserved incident artifacts, (b) the
machine's real `daemon.log`, read-only, or (c) code and test inspection. No live wedge was
reproduced; where that matters it is tagged `[MANAGER-VERIFICATION REQUIRED]`.

---

## VERDICT: fix-wave(M1, F7, F2, F5, F6, F3, F4, M2)

`89d1928`'s **dispatch-classifier half is sound and should ship**. Its **doctor half does not
fire on the only incident it was built from**, and the test that claims to pin that incident
fabricates the evidence that makes it pass. `d97f6de`, `957a4f8` and `1015344` are correct on
the substance (every receipt in them re-verified below) and carry one broken reference.

**SPURIOUS-FIX: none.** All four commits address real defects. Verification per commit in §9.

| id | sev | one line |
|---|---|---|
| **M1** | MAJOR | The doctor check cannot fire on its founding incident, and no threshold value fixes it — refusal lines are demand-driven, and the incident's whole evidence window was 161 s / 1 refusal. |
| **F7** | CRITICAL | 8 of 19 fault injections leave the suite green. The age gate — the only gate that actually discriminates — is untested in **both magnitude and sign**. |
| **F2** | MAJOR | The two halves of the feature contradict each other: `dispatch_bg` says "confirm with `fleet doctor`"; `fleet doctor` answers *no wedge signature* on that same incident. |
| **F5** | MINOR | `dispatch_bg` reads one stream where its twin `_classify_native_cli_result` reads both — a vendor stream-split silently disables the diagnosis. |
| **F6** | MINOR | An unusable `startedAt` discards refusal evidence the check can still read, retiring itself permanently on a one-key field drift. |
| **F3** | MINOR | The Windows remedy does not parse in PowerShell 5.1 (`&&`, `%VAR%`), contradicting its own "copy-pasteable on both platform families" claim. |
| **F4** | MINOR | The remedy carries no live-daemon precondition, and it instructs a destructive manual action. |
| **M2** | nit | `docs/LEDGER.md` does not exist; the ledger is `docs/PLAN-PROGRESS.md`. |

---

## M1 — MAJOR (mandated, reproduced). The doctor check cannot fire on its founding incident, and this is not a threshold bug.

### M1.a — Reproduced verbatim

```
$ py -3.13 tmp/m1_replay.py        # lock = .../scratchpad/daemon.lock.stale-pid15740.bak
                                   # log  = C:/Users/Techn/.claude/daemon.log  (read-only)
REPLAY: ('daemon-wedge', True, 'daemon.lock held by pid 15740 since 2026-07-20T23:25:28Z;
 1 late lock-race refusal(s) in the daemon.log tail (< 3) -- no wedge signature')
```

`ok=True`. Confirmed, independently, at `89d1928`. Not re-litigated.

### M1.b — The real log holds ONE refusal, and the outage's evidence window was 161 seconds

The brief asks whether the *signal* is wrong rather than the *threshold*. It is neither, exactly:
the signal is right and the **instrument** is wrong. Receipt — the real `daemon.log` across the
whole outage (`_read_tail_lines` reads the entire 51 137-byte file; the 64 KB window is not a
factor):

```
682: [2026-07-20T23:25:27.750Z] [supervisor] daemon start version=2.1.216 pid=15740 origin=transient
...
692: [2026-07-21T03:56:41.452Z] [supervisor] auth: proactive refresh succeeded      <- last sign of life
693: [2026-07-21T15:07:01.348Z] [supervisor] daemon start version=2.1.216 pid=34724 origin=transient
694: [2026-07-21T15:07:01.868Z] [supervisor] another daemon won the lock race (pid=15740) — exiting
695: [2026-07-21T15:09:42.909Z] [supervisor] daemon start version=2.1.216 pid=13500 origin=transient  <- lock removed, service restored
```

The 16-hour outage produced **exactly one** refusal line, and the entire interval in which
refusals *could* accumulate — first failed dispatch (15:07:01) to operator remedy (15:09:42) —
was **161 seconds**.

The shipped rule needs `>= 3` refusals **spanning `>= 300 s`**. On the real incident it had 1
refusal spanning 0 s. **Lowering `DAEMON_WEDGE_MIN_REFUSALS` to 1 is still not sufficient**: with
one refusal `max(refusals) - min(refusals) == 0`, so the span gate returns the PASS-note anyway.
Both count and span gates must move, and the reason is structural:

> **Lock-race refusal lines are demand-driven, not time-driven.** One is minted per *attempted
> dispatch*, never by the passage of time. A wedge on a quiet machine emits zero. The check
> therefore requires the operator to keep failing for five minutes and three attempts before it
> will speak — and an operator who has failed three dispatches over five minutes has already
> diagnosed the outage.

The docstring concedes a version of this ("a wedge is invisible here until the third refusal,
which on a quiet machine may take hours") but frames it as *lateness*. It is not lateness: on
the observed incident the operator's own remedy truncated the evidence at n=1 permanently. The
check would never have fired, at any later time, on this incident.

### M1.c — The check is strictly dominated by its own sibling in the same commit

`dispatch_bg`'s classifier fires on **attempt #1** and already names the stale lock, `fleet
doctor`, and the full remedy. The doctor check cannot reach its threshold until attempt #3.
So for the whole lifetime of a wedge:

| operator has attempted | dispatch classifier | doctor check |
|---|---|---|
| 0 dispatches (the proactive case — the one `fleet doctor` exists for) | silent | **PASS — the M1 miss** |
| 1–2 dispatches | names cause + remedy | PASS |
| ≥ 3 dispatches over ≥ 5 min | names cause + remedy | FAIL (adds nothing new) |

The check's only unique value is the top row — a `fleet doctor` run *before* dispatching, which
is precisely the state in which the log contains zero refusals. **In the row where it is the
only surface that could speak, it is structurally guaranteed to be silent.**

### M1.d — The test that claims to pin the founding incident fabricates the evidence

`tests/test_native_daemon_wedge.py:84-97`:

```python
def test_the_2026_07_21_incident_fails(self, tmp_path):
    """The one case this check exists for. ..."""
    log = INCIDENT_LOG_TAIL
    # The incident ran for ~16h; the log carried the refusal on every
    # start attempt. Three is the threshold.
    log += _refusal("2026-07-21T16:40:02.100Z", 15740)
    log += _refusal("2026-07-21T18:12:44.905Z", 15740)
```

`INCIDENT_LOG_TAIL` is genuinely verbatim and carries **one** refusal. The test then appends two
refusals that **never happened**, and the comment justifying them — *"the log carried the refusal
on every start attempt"* — is **false and falsifiable against the artifact in hand**: the real log
carries one refusal, and in the invented window (16:40, 18:12 on 2026-07-21) it shows a *healthy*
daemon serving `bg spawned` lines (lines 708–722). By 15:09:42 the lock had been removed, so a
refusal naming pid 15740 after that timestamp is not merely unobserved — it is impossible.

This is the mechanism by which M1 survived to review. The module docstring promises *"Every
fixture is fabricated **or a verbatim transcription of the manager's receipts**"*; here a verbatim
transcription is silently extended with fabrication under a comment asserting it is what the
incident did. The test named for the incident does not test the incident. **"Fault-inject your
tests or they're theater" — this fixture is the theater, one level up.**

### M1.e — A test actively pins the miss as correct behavior

`test_two_late_refusals_are_under_threshold` asserts `ok is True` for two late refusals. The
real incident produced one. The suite therefore *ratifies* the behavior that caused the 16-hour
blind spot, and any future fix to `DAEMON_WEDGE_MIN_REFUSALS` will show up as this test going
red — reading, to a later maintainer, as a regression rather than the fix.

### M1.f — The fixture defending the span gate has no real counterpart

`test_late_but_bursted_refusals_pass` justifies `DAEMON_WEDGE_MIN_SPAN_SECONDS` with *"three
clients race a HEALTHY long-lived daemon hours into its life"*, using timestamps
`15:07:01.100/.480/.868` — i.e. built by taking **the wedge's own refusal timestamp** and
inventing two siblings 768 ms earlier.

That scenario contradicts the check's own stated model. Its docstring argues:

> a lock-race refusal only happens after a client concluded no daemon was REACHABLE and launched
> a supervisor — when a healthy daemon is reachable, clients connect and no start is attempted at
> all.

If that is true — and the real log agrees — then "N clients racing a HEALTHY long-lived daemon
hours into its life" cannot occur. What *does* occur is a burst during the ~1.1 s between a
daemon's start and its socket bind (`daemon.log:682→686`), and that burst is **already** excluded
by the age gate. All three real benign races are of exactly this shape. The span gate is defended
by a fabricated scenario, and it is one of the two gates causing the miss.

### M1.g — The discriminator, specified and validated on all four real samples

**The age gate alone already is the discriminator.** Receipt — for each real refusal, the named
winner's own `daemon start` line, and the refusal's age relative to the lock that winner wrote
(derived using the one directly-observed coupling: for pid 15740, `daemon start` at 23:25:27.750Z
vs `startedAt` 23:25:28.352Z = **+0.602 s**):

```
refusal ts                    names pid   winner daemon-start           derived lock age
2026-07-14T01:15:07.492Z          28232   2026-07-14T01:15:06.243Z              0.647 s   benign
2026-07-14T06:49:12.297Z          47240   2026-07-14T06:49:11.163Z              0.532 s   benign
2026-07-17T00:35:28.269Z          39900   2026-07-17T00:35:27.217Z              0.450 s   benign
2026-07-21T15:07:01.868Z          15740   2026-07-20T23:25:27.750Z          56 493.516 s   THE WEDGE
```

Separation: **0.647 s vs 56 493.5 s — 4.9 orders of magnitude.** The existing
`DAEMON_WEDGE_MIN_LOCK_AGE_SECONDS = 300.0` sits 464× above the largest benign sample and 0.5%
of the way to the wedge. There is no calibration risk here and no false-positive pressure to
defend against: **the three benign races were never at risk of counting**, because each names a
winner that had just written the lock milliseconds earlier.

**Exact fix.**

```python
DAEMON_WEDGE_MIN_REFUSALS = 1          # was 3
DAEMON_WEDGE_MIN_LOCK_AGE_SECONDS = 300.0   # unchanged -- this is the discriminator
DAEMON_WEDGE_MIN_SPAN_SECONDS = 300.0       # unchanged, but apply only when len(refusals) >= 2
```

and in `_doctor_check_daemon_wedge`, guard the span gate:

```python
    span = (max(refusals) - min(refusals)).total_seconds()
    if len(refusals) >= 2 and span < DAEMON_WEDGE_MIN_SPAN_SECONDS:
        return ("daemon-wedge", True, ...)
```

Validated against the whole week of real log: **1 FAIL (the wedge, at 15.7 h age), 0 false
FAILs** on the three benign races.

**Why not the brief's other candidates.**

- *"In a benign race the winner keeps logging afterwards; in the wedge nothing follows."* —
  **unsound as stated.** It is an absence-of-evidence signal with no bound. On the real log,
  nothing follows a *healthy* idle-exit either (`daemon.log:707` → nothing for 7 minutes); "no
  lines after the last one" is the normal steady state of a quiet machine, not a wedge. Its
  *sound* core — that in a benign race the winner's own `daemon start` line sits ~1 s before the
  refusal, and in the wedge it sits 15.7 h before — is exactly what the age gate already measures,
  more cheaply and without a wait.
- *`roster.json` mtime staleness* — **unsound as a liveness signal, and the branch's own quoted
  number proves it.** Three blockers. (1) The path in the brief does not exist: the real file is
  `~/.claude/daemon/roster.json`, not `~/.claude/roster.json`. (2) It is **event-driven, not a
  heartbeat** — mtime tracks worker-roster changes, so on a quiet machine it goes stale while the
  daemon is perfectly healthy. (3) **Arithmetic refutation from the incident itself.** The
  substrate row quotes `roster.json: updated 45962s ago`, captured around the first failed
  dispatch (15:07:01Z):

  ```
  roster.json last written ~ 2026-07-21T02:20:59Z
  daemon last PROVEN alive  2026-07-21T03:56:41Z   (auth refresh, daemon.log:692)
  => roster.json was already 1.59 h stale while the daemon was demonstrably HEALTHY
  ```

  Any staleness threshold under 1.59 h would have fired on a healthy daemon on this very machine;
  any threshold over it buys almost nothing against a 15.7 h wedge that the age gate already
  catches with 4.9 orders of magnitude of margin. **Do not build on roster mtime.**

  The more promising sibling is `~/.claude/daemon.status.json`, which on the
  live healthy machine carries `supervisorPid: 34324` exactly matching `daemon.lock.pid`, and
  `writtenAt` 413 ms after the lock's `startedAt` — but whether the supervisor **rewrites** it
  while running, and what it contained during the wedge, are both unobserved. **Building a check
  on unverified vendor-file semantics is the exact failure this review is charging M1 with**, so
  the recommendation is: **`[MANAGER-VERIFICATION REQUIRED]` — on the next wedge, capture
  `daemon.status.json` and `daemon/roster.json` alongside `daemon.lock`.** Until then, the
  proactive gap should be *documented in the check's docstring*, not papered over.

---

## F2 — MAJOR. The two halves of the feature contradict each other on the founding incident.

`dispatch_bg`'s new message instructs the operator:

> Confirm with `fleet doctor` (the daemon-wedge check).

On the founding incident, `fleet doctor` answers `[PASS] daemon-wedge: ... no wedge signature`
(§M1.a). So the shipped instruction routes the operator to a confirmation step that, on the one
incident both halves were built from, **returns the opposite of the truth** — and the operator
who correctly trusts `fleet doctor` stays down. This is worse than the doctor check merely being
silent: it converts a correct diagnosis into a refuted one.

**Fix:** land M1.g (which makes the confirm step truthful), and until then soften the sentence —
`fleet doctor`'s daemon-wedge check corroborates only after repeated refusals; its PASS is not
evidence against a wedge.
**Test that pins it:** a test asserting that the classifier's stderr and
`_doctor_check_daemon_wedge` on the *same* incident fixture agree — i.e. feed `INCIDENT_LOCK` +
the **unmodified** `INCIDENT_LOG_TAIL` to the check and assert `ok is False`. That single
assertion is the one this branch is missing, and it is the assertion `test_the_2026_07_21_
incident_fails` was named for.

---

## F3 — MINOR. The Windows remedy does not parse in this project's primary Windows shell.

`NATIVE_DAEMON_WEDGE_REMEDY`'s docstring claims it is *"Concrete and copy-pasteable on both
platform families"*. The Windows half is `cmd.exe` syntax:

```
copy "%USERPROFILE%\.claude\daemon.lock" "%TEMP%\daemon.lock.bak" && del "%USERPROFILE%\.claude\daemon.lock"
```

Receipt, Windows PowerShell 5.1 (this project's documented primary shell, CLAUDE.md):

```
PARSE RESULT: FAILS -- The token '&&' is not a valid statement separator in this version.
literal echo of %USERPROFILE% -> %USERPROFILE%        # no expansion
```

Both the separator and the variable syntax fail. An operator following the remedy in the shell
this project actually runs gets a parse error while dispatch is down machine-wide.

**Fix:** give the PowerShell form, or a shell-neutral one:
`Copy-Item $env:USERPROFILE\.claude\daemon.lock $env:TEMP\daemon.lock.bak; Remove-Item $env:USERPROFILE\.claude\daemon.lock`
— and label the existing line `cmd.exe:` rather than `Windows:`.
**Test that pins it:** assert the remedy string contains no `&&` and no `%VAR%` token, or
(stronger) parse the Windows fragment with `[Parser]::ParseInput` in a live-tier test.

---

## F4 — MINOR (destructive direction). The remedy carries no live-daemon precondition.

`_NATIVE_BG_UNREACHABLE_RE` matches `background service did not become reachable`, which is a
**timeout**, not a stale-lock proof. Any cause of a >45 s startup — a loaded machine, an AV scan
of `claude.exe`, a slow binary-upgrade self-restart — produces the same bytes while a healthy
daemon owns the lock. Fleet then emits an unconditional imperative `REMEDY -- back up and REMOVE
the stale lock`. Deleting the singleton lock of a **live** daemon destroys the singleton
guarantee: the next `claude` start sees no lock and takes a fresh one.

**Honesty about the strength of this one:** the collision is **reasoned, not observed.** The
vendor's binary-upgrade self-restart is real and in the log (`daemon.log:164-166`, `514-516`),
but both observed instances completed in ~1.2 s — 37× under the 45 s timeout. I have no capture
of a healthy daemon exceeding 45 s, and as a `--bg` session I cannot manufacture one. What is
*not* reasoning is the asymmetry of cost: the check's own design principle is that a false
positive in a surface an operator acts on is worse than a late catch, and this is the one output
in the branch that instructs a destructive, manual, irreversible-without-backup action.

The dispatch message does hedge with *"Most likely cause"*, and the remedy does carry the backup
step — but the remedy block itself, which is also emitted verbatim by the doctor FAIL, has no
"only if" clause and no "check nothing else is running first" step. Per the brief's framing, this
is the direction to check hardest, and it is open.

**What the remedy gets right, verified:** back-up-first ✓ (`copy`/`cp` to `.bak` precedes the
delete); the `stop --any` caveat ✓ ("is NOT sufficient … does not clear the lock"); **fleet never
performs the removal itself ✓ — verified exhaustively:** `claude_daemon_lock_path()` /
`claude_daemon_log_path()` are referenced at exactly three sites (defs at 227/242 and the two
`Path(...)` resolutions at 6163–6164), the only operation applied is `read_text`, and there is no
`unlink`/`write_text`/`remove` anywhere near them.

**Fix:** precede the imperative with the precondition — *only when no `claude` session is running
and `claude daemon status` reports not-running*; and note that if a daemon **is** live the lock is
not stale and removing it is harmful.
**Test that pins it:** assert `NATIVE_DAEMON_WEDGE_REMEDY` contains a precondition token
(`only if` / `first confirm`) alongside the existing `daemon stop --any` assertion in
`test_fail_message_names_the_lock_pid_and_the_remedy`.

---

## F5 — MINOR (recurring class: a fix at one call site and not its twin).

`dispatch_bg` selects **one** stream:

```python
detail = (proc.stderr or proc.stdout or "").strip()
```

Its twin `_classify_native_cli_result`, ten screens up, reads **both**:

```python
text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
```

Receipt:

```
both on stderr (observed 2.1.216)         -> classified_as_wedge=True
both on stdout                            -> classified_as_wedge=True     (pinned by a test)
SPLIT: prefix->stderr, symptom->stdout    -> classified_as_wedge=False    <-- silent miss
```

At 2.1.216 both lines land on one stream, so this is latent, not live. But a vendor that sends
`Starting background service` to stderr and the failure to stdout silently disables the entire
diagnosis — and the branch's own stated design goal is to survive vendor wording drift.
`test_stdout_only_failure_also_classifies` pins the *empty-stderr* case only, which is the case
that already works by falling through the `or`.

**Fix:** `detail = f"{proc.stderr or ''}\n{proc.stdout or ''}".strip()`, matching the twin.
**Test that pins it:** a `_run_failing` variant with non-empty stderr *and* the symptom on stdout.

---

## F6 — MINOR. A fail-open discards evidence it can still read.

Full enumeration of the check's PASS paths (brief item 5), classified:

| PASS path | genuine unknown? |
|---|---|
| lock absent (`OSError`) | ✓ no lock ⇒ no stale lock |
| lock not JSON / not a dict | unknown, but a corrupt lock is itself a plausible wedge cause — silent |
| no usable `pid` | unknown — pid is required to attribute refusals |
| **no usable / out-of-range `startedAt`** | **✗ — see below** |
| refusals name a different pid | ✓ correct self-clearing after the remedy |
| refusal undateable (`ts is None`) | ✓ stated, and the intended POSIX degradation |
| **`len(refusals) < MIN_REFUSALS`** | **✗ — this is M1** |
| `span < MIN_SPAN` | ✗ — M1's second gate |

The `startedAt` row is a distinct fail-open from M1: when `startedAt` is missing or drifts type,
the refusals naming the lock's pid are **still fully readable and still probative**, but the age
gate cannot run so every one of them is discarded and the check returns a permanent PASS-note.
Given the branch's own premise that the vendor surface will drift, a field-shape drift in exactly
one key silently retires the check.

**Fix:** when `startedAt` is unusable, fall back to log-only evidence (refusals naming the lock's
pid, spanning `>= MIN_SPAN`, with no intervening supervisor line indicating that pid was serving)
and note the degraded confidence in the message, rather than returning immediately.
**Test that pins it:** extend the `test_field_shape_drift_passes` parametrisation with a
`startedAt`-less lock plus 3 spread refusals and assert the degraded FAIL (not PASS).

**Robustness verified, no defect:** 10/10 malformed locks — `NaN`, `±Infinity`, `1e300`,
large-negative, bigint pid, `null`, `{}`, a bare number, a BOM-prefixed body, a non-object — all
degrade to PASS-notes with **zero crashes**. This matters because `cmd_doctor` converts a raised
exception into a **FAIL**, so any crash path would silently invert the branch's stated fail-open
direction. There is none.

---

## M2 — nit (mandated). Broken reference, and the audit for others.

`docs/specs/native-substrate.md:148` cites `docs/LEDGER.md` for the 9th-live-catch receipts.

```
$ ls docs/LEDGER.md
ls: cannot access 'docs/LEDGER.md': No such file or directory
```

The ledger is `docs/PLAN-PROGRESS.md`. **Fix:** `docs/PLAN-PROGRESS.md`.

**Audit for others — the branch invented no other unresolvable reference.** Every path and
symbol introduced by the four commits was extracted from the diff and resolved:

- Files cited: `docs/specs/native-substrate.md`, `docs/reviews/MD-CONTRACT-REVIEW-2026-07-17.md`,
  `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md`, `bin/fleet.py`, `tests/conftest.py`,
  `tests/integration/test_native_pin.py`, `tests/test_native_daemon_transient.py`,
  `tests/test_native_daemon_wedge.py` — **all resolve.** Only `docs/LEDGER.md` does not.
- `_daemon_alive` (cited by `957a4f8`) — resolves, `tests/integration/test_native_pin.py:114`.
- The deleted-symbol receipt in `_doctor_check_daemon_wedge`'s docstring —
  *"`probe_liveness` / `get_process_info` / `boot_identity` … grep receipt, `bin/fleet.py`
  @ac3e34d: zero matches"* — **verified true**: 0/0/0 at `ac3e34d`; the only matches at HEAD are
  the docstring's own mention (`6139-6140`).

---

## §9 — SPURIOUS-FIX verdict, per commit (mandatory)

| commit | claim | verdict |
|---|---|---|
| `d97f6de` n2 | `native_short_id`'s stated provenance is false on 2 of its 6 write paths | **REAL.** Write sites re-grepped: `2378, 2450, 3468, 3939, 3980, 6617` = 6 (line 684 is the schema default, not a write); `fast_sid.partition` at `2378, 3939` = 2. The builder's receipt is exact. |
| `d97f6de` n3 | the streak resets on "deferred nothing", not "removed a husk" | **REAL.** Code is `if deferred <= 0: break` — `removed` is never consulted. The old comment's justification ("a single successful sweep means the daemon was reachable") was genuinely false. |
| `d97f6de` n4 | the note fires **on** the 3rd starved sweep, not after it | **REAL.** `if husks_deferred > 0 and streak >= AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD` (`5994`), `THRESHOLD = 3`. |
| `89d1928` classifier | names the stale-lock cause on the unreachable-service stderr | **REAL and effective** — see §Own-hunt-1. |
| `89d1928` doctor check | detects the wedge | **REAL problem, INEFFECTIVE fix** — M1. Not spurious: the outage and the blind spot are both real; the detector simply cannot reach its own threshold. |
| `957a4f8` ND-4 | name the false-SKIP the ND-2 fix introduced | **REAL** — see §Own-hunt-7. |
| `1015344` | record the PID-reuse wedge as a substrate hazard | **REAL.** Corroborated independently: the row's *"`fleet doctor` reported 21 PASS / 0 FAIL"* checks out — `check_calls` holds exactly **21** entries at `ac3e34d` and **22** at `me/daemon`. |

**No commit in this branch fixes a non-problem. SPURIOUS-FIX: none.**

---

## Own hunt — items 1–8

**1. The dispatch classifier.** Probed with 11 strings against the real 2.1.216 stderr:

```
case                                           BG_UNREACH  CLI_TRANSIENT  CLI_GONE
REAL 2.1.216 stderr (verbatim)                       True          False     False
REAL, em-dash variant                                True          False     False
REAL, curly apostrophe                               True          False     False
REAL, upper-cased                                    True          False     False
only the wrapper sentence                            True          False     False
only the inner sentence                              True          False     False
timeout reworded 90s                                 True          False     False
healthy prefix ALONE (must NOT match)               False          False     False
rm transient (must NOT match)                       False           True     False
gone (must NOT match)                               False          False      True
line-split mid-phrase                               False          False     False
```

Matches the exact real string; both halves independently sufficient as designed; survives dash,
apostrophe, case and timeout variation. **The destructive direction the brief flagged is clean at
the regex level:** `_NATIVE_CLI_TRANSIENT_RE`'s string (`background service may be restarting`)
does **not** match `_NATIVE_BG_UNREACHABLE_RE`, and vice versa — a transient restart cannot be
captured as a wedge *by wording*. It can by *timeout* — that is F4, a semantic overlap the regex
cannot fix. Two gaps: F5 (split streams) and a hard-wrapped mid-phrase newline (nit; a terminal
soft-wrap does not insert a byte, so this is only reachable if the vendor hard-wraps).

**2. The remedy text.** See F3 (PowerShell), F4 (missing live-daemon precondition, plus the
verified-correct backup and `stop --any` caveats), and the exhaustive verification that **fleet
never removes the lock itself** — read-only at both call sites, zero write/unlink operations.

**3. `tests/conftest.py`.** Clean, with one caveat worth recording. The two new monkeypatches
redirect the module-level path functions, and `_doctor_check_daemon_wedge` resolves them at call
time, so the redirection holds. **No test reads the developer's real `~/.claude` for these two
paths.** The vacuous-pass question comes back negative: no pre-existing test counts doctor checks
or asserts an all-PASS `fleet doctor`, so the sandbox default (an empty `.claude/` where neither
file exists ⇒ the absent-lock PASS-note) cannot silently satisfy an existing assertion. Caveat:
that default means every doctor test *other* than the new ones exercises the wedge check only via
its absent-lock branch — acceptable, but it is the reason a `cmd_doctor`-level regression would
be caught solely by `test_registered_with_the_other_doctor_checks`.

**4. Fault injection.** See §F7 below — 19 mutations, 11 RED / 8 GREEN.

**5. Fail-open audit.** Full enumeration in F6. Three fail-opens can mask a real wedge: the
`MIN_REFUSALS`/`MIN_SPAN` pair (M1, confirmed on the real incident), the `startedAt` shape drift
(F6), and an unreadable/corrupt lock (inherent — nothing to attribute refusals to). All other
PASS paths are genuine unknowns.

**6. The nits commit (`d97f6de`).** All three re-asserted against the code they now describe;
all three correct. Receipts in §9. The n2 grep receipt was re-run independently, not read.

**7. ND-4 (`957a4f8`).** The review asked for two things. **It did (1)** — the false-SKIP is now
named in full, with its exact causal chain, in `test_native_pin.py`. **It declined (2)** (sampling
`_daemon_alive()` before the archive) and the stated reasoning is **sound**, verified on both
grounds:

- *It would mint a new false-RED.* Confirmed by reading the branch condition: pre-sample alive →
  daemon idle-exits → dead at rm → `deferred (failed)` under a drifted message → `rm_unclassified`
  → "both samples dead" unsatisfied → hard assert, on a machine whose daemon was merely down. The
  fix brief permitted (2) only if it "cannot itself introduce a new false-RED". It can, so
  declining is the correct call.
- *The probe is not passive.* Confirmed: `_daemon_alive()` runs `claude daemon status`
  (`test_native_pin.py:114-128`), which connects as a client, and the daemon idle-exits ~5 s after
  the last client disconnects. A pre-archive probe therefore perturbs the very lifetime it
  measures. This argument is correct and is the stronger of the two.

No new false-RED was introduced, because nothing executable changed — `957a4f8` is comment-only.

**8. Recurring classes.**

- *A fix at one call site and not its twin* — **found: F5.**
- *A fix that mints a new defect one call site away* — **not found.** The n2 comments were added
  at both fast-completion sites (`2378`, `3939`); the remedy constant is shared by both surfaces
  by construction, which is the right shape.
- *A comment that lies* — **found: M1.d** (the fabricated-fixture comment). Separately, the
  `_parse_daemon_log_ts` docstring's 3.10 justification was **independently verified true**, not
  taken on trust: `datetime.fromisoformat("2026-07-21T15:07:01.868Z")` → `REJECTED (Invalid
  isoformat string)` on 3.10.1, `ACCEPTED` on 3.13.
- *3.10-floor break* — **none.** `git show me/daemon:bin/fleet.py` imports and runs clean on
  `py -3.10` (3.10.1): all four `_parse_daemon_log_ts` shapes correct, the end-to-end wedge check
  returns the same verdict as 3.13, `_NATIVE_BG_UNREACHABLE_RE` matches. The `strptime`-over-
  `fromisoformat` choice is the right one and is the reason.
- *An enumeration built by reading instead of grep* — **none found**; every enumeration in the
  branch (n2's 6 sites, the deleted-symbol receipt) was re-derived by grep here and matched.
- *Views never probe* — **clean.** The new helpers and check are referenced only from
  `cmd_doctor`'s `check_calls` and `dispatch_bg`. `status_snapshot`, the statusline script and the
  `/fleet:*` surfaces touch none of them.
- *Doctor must never write* — **clean**, verified above and pinned by `test_check_mutates_nothing`
  (bytes **and** mtime **and** directory listing).
- *Portability invariant 8* — the code degrades correctly rather than asserting a POSIX result:
  pure `Path.home()` + `read_text` + `re`, no platform branch, and a POSIX filename or log-format
  drift lands on the undateable/absent-file PASS-notes, which is the stated intended direction.
  The `[UNVERIFIED — no POSIX box]` tags are present and honest.

---

## F7 — CRITICAL. Fault injection: 8 of 19 mutations leave the suite green.

Method: one mutation at a time into `bin/fleet.py`, full suite (`py -3.13 -m pytest -q -x`),
`git checkout -- bin/fleet.py` between each. Per the brief's standing rule, *any* injection
leaving the suite green is CRITICAL — the test is theater. Worktree verified clean after the
run, and the suite re-verified at **1170 passed / 6 skipped**.

**19 mutations, 11 RED / 8 GREEN.** Brief requires a minimum of 8; every threshold, the
lock-parse path, the log-tail parse, the pid match, the classifier regex and the PASS-note
fail-open branches are covered as required.

| # | mutation | suite |
|---|---|---|
| I1 | `DAEMON_WEDGE_MIN_REFUSALS` 3 → 1 | RED |
| **I2** | **`DAEMON_WEDGE_MIN_LOCK_AGE_SECONDS` 300.0 → 0.0** | **GREEN** |
| I3 | `DAEMON_WEDGE_MIN_SPAN_SECONDS` 300.0 → 0.0 | RED |
| I4 | drop the pid-match gate entirely | RED |
| I5 | drop the fractional-seconds timestamp format | RED |
| I6 | `startedAt` time base: millis read as seconds | RED |
| I7 | `_NATIVE_BG_UNREACHABLE_RE` never matches | RED |
| I8 | `_NATIVE_BG_UNREACHABLE_RE` matches everything | RED |
| I9 | refusal-count comparison `<` → `<=` | RED |
| I10 | span comparison inverted | RED |
| I11 | undateable refusal → `ts = started` | GREEN *(weak mutation — neutralised by the age gate; re-run sharpened as I11b)* |
| **I11b** | **undateable refusal → `ts = started + 1 day` (fail-open → evidence)** | **GREEN** |
| **I12** | **lock-race regex loses its literal phrase (`another daemon won the …`)** | **GREEN** |
| **I13** | **`isinstance(pid, bool)` guard removed** | **GREEN** |
| **I14** | **`dispatch_bg` stream precedence `stderr or stdout` → `stdout or stderr`** | **GREEN** |
| I15 | remedy loses the `stop --any is NOT sufficient` caveat | RED |
| I16 | absent-lock PASS-note flipped to FAIL | RED |
| **I19** | **`_DAEMON_LOG_TS_RE` prefix anchor `^` dropped** | **GREEN** |
| **I20** | **age gate made absolute (`abs(...)`) — pre-lock history counts** | **GREEN** |

### The GREEN results are not independent — they share one cause

**I2 and I20 are the headline, and together they corroborate M1 exactly.** No test in the entire
1170 depends on `DAEMON_WEDGE_MIN_LOCK_AGE_SECONDS` having any value at all (I2), *and* none
depends on the age comparison being signed rather than absolute (I20). **The age gate — which
§M1.g shows is the only gate that actually discriminates the wedge from the three real benign
races — is untested in both magnitude and sign.** I20 matters on its own: with an absolute
comparison, refusal history from *before* the current lock was written would indict it, which is
exactly the self-clearing property `test_refusals_naming_a_different_pid_pass` claims to protect
— that test uses a different pid (99999), so the same-pid-older-history case is uncovered.

Direct probe of the test that is *named* for the age gate:

```
test_genuine_startup_race_passes fixture:
   shipped                       -> ok = True
   with AGE gate disabled (0.0)  -> ok = True   <- the SPAN gate is what passes it
   with SPAN gate disabled (0.0) -> ok = True   <- the age gate alone would also pass it
```

The same mechanism explains **I11b** (`test_undated_refusal_lines_pass`: with undateable lines
forced to count, all five share one timestamp ⇒ span 0 ⇒ the span gate passes it anyway) and
**I13** (`test_field_shape_drift_passes[pid=True]`, commented `# bool is not a pid`, feeds
refusals naming 15740, which can never equal `True`; the guard is never reached — a refusal
naming `pid=1` is required, since `1 == True` in Python).

So **three tests named for three different properties are all actually held up by the span
gate**, and the properties they advertise are untested.

> **Consequence for the fix wave, and it is the sharpest practical point in this review:** the
> M1.g fix *relaxes the span gate* — the only gate with real coverage — and makes the age gate
> load-bearing. Shipping M1.g without simultaneously adding age-gate coverage would move the
> feature from "wrong but tested" to "right but untested". **M1.g must land together with:** a
> test asserting a late-but-single refusal FAILs — this is the M1 regression test, and it is
> exactly `_check(tmp_path, INCIDENT_LOCK, INCIDENT_LOG_TAIL)` with the fabrication of §M1.d
> removed; a test asserting a sub-second startup race still PASSes *with the span gate disabled*;
> a test asserting refusals dated **before** the lock's `startedAt` never count (kills I20); a
> `pid=1` case for the bool guard; and an undateable-line test that does not depend on span.

**I14** is F5 reproduced empirically: the stream-selection expression in `dispatch_bg` is
untested, because the only test in the area (`test_stdout_only_failure_also_classifies`) sets
`stderr=""`, which is the case that works by falling through the `or` regardless of order.

**I12** and **I19** are the two smallest: the lock-race regex's literal phrase and the timestamp
regex's `^` anchor are both untested, so any log line containing `lock race (pid=N)` or an
embedded ISO timestamp would be consumed. Low severity — no such vendor line is known — but
both are one-line test additions.

---

## Ratification

Nothing is ratified here. The `[OBSERVED 2.1.216 — PENDING OPERATOR RATIFICATION]` row in
`docs/specs/native-substrate.md` **stays pending**; that gate is the operator's alone. This review
adds one item to the operator's open list for that row: alongside re-capturing the wedge to
calibrate the thresholds, **capture `~/.claude/daemon.status.json` and
`~/.claude/daemon/roster.json` at the same moment** — they are the only candidates that could
close the proactive gap in M1.c, and neither can be specified from the artifacts now in hand.

---
---

# FINAL GATE — wave 1 (`bf26e74`, `d13b012`)

**Gate run:** 2026-07-21, same reviewer, same worktree. Wave merged here as `54c69d3`
(`me/daemon` @ `d13b012` into `me/daemon-review`). Suite in this worktree: **1200 passed /
6 skipped** (wave base 1170).

**Probe context, unchanged:** this reviewer is a `--bg` session and is by construction a live
daemon client, so it **cannot reach the wedged state**. Every FAIL-direction result below comes
from the preserved incident artifacts or from the machine's real, read-only `daemon.log`. A live
end-to-end wedge reproduction remains **[MANAGER-VERIFICATION REQUIRED]**.

## VERDICT: fix-wave(ND-1)

Eight of eight findings are **FIXED**, several better than asked. The wave is careful, honest
work: the fixture fraud that caused M1 is genuinely gone, the ratifying test was inverted rather
than deleted, and one of the two GREEN injections is a correct equivalent-mutant call.

It is not mergeable, because it minted one new defect of exactly the class it was fixing.

**ND-1 (MAJOR, blocking): the wedge verdict is non-monotonic in evidence.** One late refusal
FAILs; two late refusals *thirty seconds apart* PASS. The check detects the founding incident in
its exact preserved shape and **un-detects it the moment anyone retries a dispatch inside five
minutes** — the most likely operator action there is. And, as with the original M1, a test
asserts the miss is correct.

The fix is one line plus one test inversion, and **the wave's own tests already prove it safe**
(§ND-1.d). This is a fix-wave, not an ESCALATE: the defect is single, precisely located, and its
remedy is already validated by evidence sitting in the branch.

---

## Manager truth gate — all three claims verified

| claim | verdict |
|---|---|
| Preserved stale lock + **unmodified** real `daemon.log` -> `ok=False`, precondition-first remedy | **CONFIRMED** |
| Live healthy machine -> `[PASS] daemon-wedge ... 0 late lock-race refusal(s) ... no wedge signature` | **CONFIRMED** |
| Suite 1200 passed / 6 skipped (base 1170) | **CONFIRMED** |

```
$ py -3.13 tmp/gate.py     # lock = preserved .bak ; log = C:/Users/Techn/.claude/daemon.log
=== TRUTH GATE 1: preserved lock + UNMODIFIED real daemon.log ===
 ok = False
 msg: the Claude background daemon looks WEDGED: 1 daemon start(s) were refused by
 ~/.claude/daemon.lock (pid 15740, held since 2026-07-20T23:25:28Z); the most recent, at
 2026-07-21T15:07:01Z, was refused by a lock already 15.7h old ...
 remedy opens with PRECONDITION? True

=== TRUTH GATE 2: live healthy machine (defaults) ===
 ok = True | daemon.lock held by pid 34324 since 2026-07-21T15:17:28Z; 0 late lock-race
 refusal(s) in the daemon.log tail (< 1) -- no wedge signature
```

The manager is right on all three. Note what gate 2 additionally proves: the live log **still
contains the wedge's own refusal line** (naming the now-replaced pid 15740), and `MIN_REFUSALS=1`
does **not** false-FAIL on it — the pid-match gate self-clears exactly as designed.

---

## ND-1 — NEW DEFECT, MAJOR, blocking

### ND-1.a — The receipt

`bin/fleet.py:6324`, primary path:

```python
    if len(late) >= 2 and span < DAEMON_WEDGE_MIN_SPAN_SECONDS:
        return ("daemon-wedge", True, ... "one burst, not a wedge")
```

`INCIDENT_LOCK` (the preserved artifact) with late refusals appended:

```
1 late refusal (the REAL incident)            -> ok=False  FAIL (detected)
2 late refusals 29s apart (operator retried)  -> ok=True   PASS (MISSED)
2 late refusals 2min apart                    -> ok=True   PASS (MISSED)
2 late refusals 6min apart                    -> ok=False  FAIL (detected)
3 late refusals 30s apart                     -> ok=True   PASS (MISSED)
```

**Adding evidence makes the verdict weaker.** A wedge is reported if you attempt one dispatch, or
two more than five minutes apart, but *not* if you attempt two within five minutes. The verdict
depends on the operator's retry cadence rather than on the evidence.

### ND-1.b — Reachable on the founding incident, not an exotic shape

The real outage's evidence window was 161 s (first failed dispatch `15:07:01.868Z` -> operator
remedy `15:09:42.909Z`). **Any** second dispatch attempt inside that window — a retried
`fleet spawn`, a second worker, another worktree, a plain interactive `claude` — mints a second
refusal and flips the verdict from FAIL to PASS. With seven live worktrees during a machine-wide
outage this is closer to certain than to likely. The only reason the real log holds a single
refusal is that the operator diagnosed it in under three minutes.

Fleet's own `dispatch_bg` does not retry a non-zero return (it raises immediately), so fleet alone
will not trip this — but nothing prevents a human or a sibling worker from doing so.

### ND-1.c — A test ratifies the miss, exactly as the original M1 was ratified

`tests/test_native_daemon_wedge.py::test_a_late_burst_of_refusals_passes` asserts `ok is True`
for three refusals at `15:07:01.100/.480/.868` — all ~15.7 h after the lock's `startedAt`, i.e.
all *late*. Its own docstring concedes the shape is imaginary:

> **CONSTRUCTED, and labelled as such: no burst of this shape has ever been observed.** Every real
> burst sits inside the ~1.1s between a daemon's start and its socket bind, which the age gate
> already excludes. ... this test pins that it is still wired, not that the scenario is real.

That is a correct description of an unnecessary gate, followed by a test that ratifies the miss it
causes — structurally identical to `test_two_late_refusals_are_under_threshold`, the test this
same wave rightly inverted. The honesty is real and creditable; the conclusion drawn from it is
the wrong one.

### ND-1.d — Exact fix, already validated by the branch's own tests

**Drop the span gate from the PRIMARY path.** Keep it in the F6 degraded path, where no age gate
exists and it is the only discriminator.

```python
-    span = (max(late) - min(late)).total_seconds()
-    if len(late) >= 2 and span < DAEMON_WEDGE_MIN_SPAN_SECONDS:
-        return ("daemon-wedge", True, ...)
```

Justification, all of it already in the branch:

1. The age gate excludes every real benign race by 4.9 orders of magnitude (0.647 s vs 56 493.5 s).
2. By the check's own stated model, a refusal only occurs after a client found no daemon
   *reachable*. Two or more such events **>=300 s after the lock was written** mean the lock's
   holder is not serving. That is a wedge, burst or not.
3. **The wave already ships the proof.** `test_real_benign_races_pass_with_the_span_gate_disabled`
   forces `MIN_SPAN = 0` and asserts all three real benign races still PASS;
   `test_the_incident_fails_with_the_span_gate_disabled` asserts the incident still FAILs. With the
   span gate disabled the suite's real-world fixtures already behave correctly — which is exactly
   the evidence that the primary-path span gate earns nothing.

**Test to pin it:** invert `test_a_late_burst_of_refusals_passes` (assert `ok is False`) with a
docstring naming what it replaced, exactly as `test_two_late_refusals_spanning_hours_fail` did —
plus a direct case for the real incident **plus one retry 30 s later**, asserting `ok is False`.

### ND-1.e — The counter-argument, stated and answered

Dropping the primary span gate does widen one exposure, and it deserves saying out loud rather
than being waved past. **It is the only argument for keeping the gate, and it does not survive.**

The scenario: a *healthy* daemon holds the lock, and two or more clients fail to reach it within
five minutes, each >=300 s after that daemon started — say a transient named-pipe connect failure
under resource exhaustion. Today the span gate returns PASS; without it the check FAILs.

Three reasons that is the right trade:

1. **Zero occurrences in a week of real log.** All four lock-race refusals the machine has ever
   recorded are either the wedge or sub-second startup races. The shape is constructed — which the
   wave's own docstring already concedes.
2. **The FAIL would still be true.** What the check reports is *the daemon was not reachable and
   every dispatch is failing*. In this scenario that is exactly what happened. Fleet does not care
   whether the holder is dead or merely unreachable; dispatch is down either way.
3. **F4's precondition already contains the blast radius, and this is why F4 matters.** The
   dangerous consequence of a false FAIL is an operator deleting a live daemon's lock. The remedy
   now refuses to authorise that: it fires only if `claude daemon status` reports `not running`.
   In the healthy-but-unreachable case the operator sees a live daemon, the precondition fails,
   and they correctly do not remove the lock. **The wave's own F4 fix is what makes the looser
   FAIL safe** — the two changes are complements, and shipping F4 while keeping the span gate
   takes the cost of both and the benefit of neither.

Against that: with the gate retained, the check silently misses the founding incident under the
most likely operator behaviour there is. A conservative gate that produces a *silent PASS on a
real machine-wide outage* is not conservative; it is the M1 failure wearing a different mask.

---

## Dispositions

| id | disposition | evidence |
|---|---|---|
| **M1** | **FIXED** | `MIN_REFUSALS 3->1`; span gate guarded to `n>=2`; age gate unchanged and now named as the discriminator. Preserved lock + unmodified real log -> `ok=False`. Pinned by `test_the_real_incident_artifacts_fail` on the **unmodified** `INCIDENT_LOG_TAIL`. ND-1 attacks a variant, not this repro. |
| **F7** | **FIXED** | Injection table re-run below. The three tests that were secretly held up by the span gate are re-pinned, and the age gate is now pinned in **magnitude** (`test_real_benign_races_pass_with_the_span_gate_disabled`, plus 299 s/301 s boundary probes) and in **sign** (I20 RED). |
| **F2** | **FIXED** | `test_dispatch_and_doctor_agree_on_the_real_incident` drives both halves off one artifact and asserts doctor does not contradict the dispatch message. The message additionally warns that if doctor reports no wedge the lock must **not** be removed — the string is a 45 s timeout, not proof. Better than asked. |
| **F5** | **FIXED** | `detail = f"{proc.stderr or ''}\n{proc.stdout or ''}"`, matching the twin. Both single-stream regressions go RED (I14a, I14b). |
| **F6** | **FIXED** | Degraded FAIL **reachable for all 7 shapes** (absent / None / str / bool / NaN / +inf / 1e300) and correctly quiet at 1 refusal and at 2 refusals 30 s apart. The unimplemented "no intervening supervisor line" clause is declined in the docstring with a stated reason — the correct call. |
| **F3** | **FIXED** | Independently re-verified, not taken from the commit message: `[Parser]::ParseInput` -> **OK (0 errors), PSVersion 5.1.19041.7548**; `$env:USERPROFILE` -> `C:\Users\Techn`. cmd.exe form kept and labelled rather than dropped. |
| **F4** | **FIXED** | Remedy opens `PRECONDITION FIRST: only if NO claude session is running and claude daemon status reports not running`, and states removal is HARMFUL against a live daemon. **Correct, not merely present:** consistent with the incident, where `daemon status` answered `not running`. Live re-verification is barred by containment -> **[MANAGER-VERIFICATION REQUIRED]**. |
| **M2** | **FIXED** | `docs/LEDGER.md` -> `docs/PLAN-PROGRESS.md`; resolves. |

**No regressions. No SPURIOUS-FIX.** Every one of the eight addresses the defect it names.

---

## Fixture audit — the root cause of how M1 shipped green

**CLEAN — zero fabricated lines.** Verified mechanically, not by reading labels: every
`VERBATIM`-claimed string was matched against `C:/Users/Techn/.claude/daemon.log`, and
`INCIDENT_LOCK` against the preserved `.bak`.

```
INCIDENT_LOCK identical to the .bak byte content: True

[INCIDENT_LOG_TAIL]      VERBATIM (real log line 682)   daemon start pid=15740
[INCIDENT_LOG_TAIL]      VERBATIM (real log line 693)   daemon start pid=34724
[INCIDENT_LOG_TAIL]      VERBATIM (real log line 694)   another daemon won the lock race (pid=15740)
[REAL_BENIGN_RACES[0]]   VERBATIM (real log line 149)   daemon start pid=28232
[REAL_BENIGN_RACES[0]]   VERBATIM (real log line 154)   ... (pid=28232)
[REAL_BENIGN_RACES[1]]   VERBATIM (real log line 167)   daemon start pid=47240
[REAL_BENIGN_RACES[1]]   VERBATIM (real log line 170)   ... (pid=47240)
[REAL_BENIGN_RACES[2]]   VERBATIM (real log line 517)   daemon start pid=39900
[REAL_BENIGN_RACES[2]]   VERBATIM (real log line 520)   ... (pid=39900)

>>> fabricated lines among VERBATIM-claimed fixtures: 0
```

All nine land at exactly the claimed line numbers. The only other refusal-shaped literals in the
file are the `_refusal()` helper (labelled CONSTRUCTED) and two undated probes. The module
docstring now carries the rule it violated — *"when the real artifact is in hand, the fixture IS
the real artifact"* — and names the original fabrication explicitly. **This is the most important
thing the wave got right.**

**`test_two_late_refusals_are_under_threshold` was INVERTED, not deleted** — it is now
`test_two_late_refusals_spanning_hours_fail`, asserting `ok is False`, with a docstring recording
that the old version had *"RATIFIED the M1 blind spot as correct behavior"*. Correct handling.

## I15 — credit, verified

The self-report is accurate. The wave's own rewrite had loosened the caveat assertion to
`not sufficient|does not (clear|remove)`, an alternation that survived deleting the sentence, so
the caveat looked pinned and was not. It is now pinned as bytes at
`tests/test_native_daemon_wedge.py:474`:

```python
assert "`claude daemon stop --any` is NOT sufficient" in remedy
```

Finding its own regression and fixing rather than arguing it is the right instinct, and it is what
a self-reported GREEN is *for*.

## Disputes — ruled

**I19 (`^` anchor dropped) — UPHELD. A genuine equivalent mutant.**
`_DAEMON_LOG_TS_RE` has exactly one call site, `.match` (`bin/fleet.py:6144`), which anchors at
position 0 by definition; `re.MULTILINE` is not set, so the caret matches nowhere else either. I
probed both patterns over seven strings including the two the finding cares about:

```
'[2026-07-21T15:07:01.868Z] x'   match-equal=True      'a\n[2026-07-21T15:07:01.868Z]'  match-equal=True
'x [2026-07-21T15:07:01.868Z]'   match-equal=True      ''                               match-equal=True
'  [2026-07-21T15:07:01.868Z]'   match-equal=True      '[[2026-07-21T15:07:01.868Z]'    match-equal=True
>>> distinguishing inputs found via .match: 0
```

No test can kill a mutant with no observable difference, so its GREEN is not theater. Keeping the
caret for documented intent is the right call.

**I11 (`ts = started`) — the equivalence claim is REJECTED; the supersession stands.**
The justification is **stale: it describes the pre-wave code.** Under the old inline age filter it
was sound. Under the code this wave shipped, `refusals` is collected *unfiltered* and also feeds
the F6 degraded path, where `started is None`. The mutant therefore appends `None`:

```
degraded path (startedAt unusable => started=None), 3 UNDATED refusals:
  original refusals: []
  mutant   refusals: [None, None, None]
  mutant verdict: *** TypeError: '>' not supported between instances of 'NoneType' and 'NoneType' ***
  original verdict: (True, '... 0 lock-race refusal(s) naming it (< 2) -- not enough ...')
```

A distinguishing input exists, so I11 is **not** an equivalent mutant. The specific sentence that
is wrong is *"On the F6 degraded path `started` is None, so `ts` is None and the line is skipped
there too"* — it is not skipped; it is appended as `None`. What actually carries the row is the
builder's own supersession by **I11b, which is RED**: the right outcome reached through a wrong
argument, and the argument is the sort that must not stand as precedent.

*(No live defect: `refusals` can only ever contain `datetime`s, so the crash is reachable only
under mutation.)*

## Injection table — re-run independently

Method unchanged: one mutation at a time into `bin/fleet.py`, **full `tests/`** each, file restored
via `git checkout --` between every row. Anchors rebuilt from scratch rather than copied from the
wave, and three rows re-run separately after my own anchor-escaping errors.

**Result: 24 RED / 2 GREEN of 26. Both GREEN are the two disputed rows. Every direction matches
the builder's table.**

| # | mutation | suite |
|---|---|---|
| I1 | `MIN_REFUSALS` 1→3 (restores the M1 miss) | RED (9 failed) |
| I2 | `MIN_LOCK_AGE_SECONDS` 300.0→0.0 | RED (7) |
| I3 | `MIN_SPAN_SECONDS` 300.0→0.0 | RED (2) |
| I4 | pid-match gate dropped | RED (2) |
| I5 | fractional-seconds ts format dropped | RED (15) |
| I5b | fraction**less** ts format dropped | RED (1) |
| I6 | `startedAt` time base: millis read as seconds | RED (9) |
| I7 | `_NATIVE_BG_UNREACHABLE_RE` never matches | RED (8) |
| I8 | `_NATIVE_BG_UNREACHABLE_RE` matches everything | RED (2) |
| I9 | refusal-count comparison `<` → `<=` | RED (8) |
| I10 | span comparison inverted | RED (2) |
| **I11** | **undateable refusal → `ts = started`** | **GREEN — disputed, see ruling** |
| I11b | undateable refusal → `ts = started + 1 day` | RED (2) |
| I12 | lock-race regex loses its literal phrase | RED (1) |
| I13 | `isinstance(pid, bool)` guard removed | RED (1) |
| I14a | `dispatch_bg` reads stderr only (pre-F5) | RED (2) |
| I14b | `dispatch_bg` reads stdout only | RED (8) |
| I15 | remedy loses the `stop --any` caveat | RED (4) |
| I16 | absent-lock PASS-note flipped to FAIL | RED (2) |
| **I19** | **`_DAEMON_LOG_TS_RE` prefix anchor dropped** | **GREEN — disputed, see ruling** |
| I20 | age gate made absolute | RED (1) |
| I21 | span-gate `len(late) >= 2` guard removed | RED (7) |
| I22 | F6 degraded path never reaches a verdict | RED (7) |
| I23 | remedy loses the F4 precondition | RED (1) |
| I24 | remedy reverts to cmd.exe-only Windows form | RED (2) |
| I25 | F6 degraded verdict flipped to PASS | RED (7) |

**F7 is FIXED.** The three properties that were previously held up by the span gate are now
independently pinned: I2 (age-gate magnitude) and I20 (age-gate **sign**) both go RED where both
were GREEN last wave, and I13 goes RED where it was GREEN — the `pid=1` fixture the wave added is
what reaches the bool guard, since no other pid can.

**Counting nit.** The commit message reads *"24 mutations, one at a time … 22 RED / 2 GREEN"*, and
the manager's brief inherited the figure as "now 24". The table actually lists **26** rows, and the
correct tally is **24 RED / 2 GREEN**. Rows and directions are right; only the arithmetic in the
summary line is wrong. My per-row failure *counts* differ from the builder's on four rows
(I1 9 vs 8, I6 9 vs 8, I9 8 vs 7, I15 4 vs 1) — a scope/ordering artifact, not a disagreement:
every RED/GREEN direction matches.

---

## New-defect hunt

Five of the last five waves in this project minted a defect. **This one did too: ND-1**, above.
The manager named five aim points; here is each, with the negative results stated as plainly as the
positive one.

| target | result |
|---|---|
| **the `len(refusals) >= 2` span-guard boundary** | **ND-1 — MAJOR, blocking.** The one hit. |
| the signed age comparison | **Clean.** Refusals at −1 s, −1 h and −15.7 h relative to the lock are all correctly ignored; boundary is inclusive exactly as the constant reads (299 s → PASS, **300 s → FAIL**, 301 s → FAIL). Pinned by I20 (RED) and both boundary tests. |
| the `startedAt`-unusable degraded path — reachable *and* correct? | **Clean, both.** The degraded FAIL is reachable for all **7** shapes (absent, `None`, `str`, `bool`, `NaN`, `+inf`, `1e300`) and correctly quiet below its own threshold (1 refusal → PASS; 2 refusals 30 s apart → PASS; 2 refusals 3 h apart → FAIL). Pinned by I22 and I25 (both RED). |
| F5's `detail` change + the 7 neighbouring stream sites it claims to have audited | **Change correct; the enumeration is not.** See below. |
| the remedy's new precondition — *correct*, not merely present? | **Correct.** It authorises removal only when `claude daemon status` reports `not running`, which is exactly what the incident capture recorded. It also correctly withholds authorisation in the healthy-but-unreachable case — the property that makes ND-1's fix safe (§ND-1.e). Live re-verification is barred by containment → **[MANAGER-VERIFICATION REQUIRED]**. |

### F5 twin audit — right answer, wrong enumeration (nit)

The commit cites *"every neighbouring stream selection (338/362/374/4714/7150/7502/7777)"*. Two of
those seven are not stream selections at all — **7502** is `except Exception as exc:` and **7777**
is an f-string tail — and the list omits roughly ten real ones: 327, 328, 339, 5494, 5554, 5678,
5700, 7154, 7506, 7781, 7789. This is the *enumeration-built-by-reading-instead-of-grep* class the
original brief calls out.

**The conclusion nevertheless holds, and I verified it rather than assuming it.** No other matcher
reads a single stream:

- `_classify_native_cli_result` (4714) — both streams, correct (the twin).
- `_NATIVE_BG_UNREACHABLE_RE` in `dispatch_bg` (7127) — both streams, correct (the F5 fix).
- `_parse_claude_version` (5494, 5554) — `stdout + stderr`, correct.
- `_parse_bg_short_id` (7151, **7789**) — `stdout` only, and contractually so. 7789 is the
  fork-steer copy of the same shape and is **not** in the cited list, though it has the identical
  justification.
- 362/374 (`schtasks` create/delete), 327/338/5678/5700/7506/7781 — operator-facing echoes with no
  matcher reading them, exactly as claimed.

So: a nit against the receipt, not against the fix. Recorded because a receipt that cannot be
re-derived is the thing that lets the next enumeration be wrong in a way that matters.

---

## Invariants re-confirmed on the changed code

- **3.10 floor — CLEAN.** `py -3.10` (3.10.1) imports the wave's `bin/fleet.py`, returns the same
  `ok=False` on the incident artifacts as 3.13, parses both stamp shapes, and drives the **new F6
  degraded path** to the same verdict. Control re-run, not taken on trust:
  `datetime.fromisoformat("2026-07-21T15:07:01.868Z")` → **REJECTED** on 3.10.1, **ACCEPTED** on
  3.13 — which remains the reason `_parse_daemon_log_ts` uses `strptime`.
- **Views never probe — CLEAN.** `claude_daemon_lock_path` / `claude_daemon_log_path` /
  `_doctor_check_daemon_wedge` / the new `_daemon_wedge_degraded_verdict` are reachable only from
  `cmd_doctor`'s `check_calls` and `dispatch_bg`. `status_snapshot`, the statusline script and the
  `/fleet:*` surfaces touch none of them.
- **Doctor never writes — CLEAN.** Both paths are `read_text` only; zero `unlink` / `write_text` /
  `mkdir` / `remove` anywhere near them. Pinned by `test_check_mutates_nothing` (bytes, mtime and
  directory listing).
- **Ratification markers — UNTOUCHED, 8 → 8.** `docs/specs/native-substrate.md` carries 8
  `PENDING OPERATOR RATIFICATION` markers at `1015344` and 8 at `d13b012`, including the 2.1.216
  wedge row's own. **I ratified nothing.** The row remains the operator's gate alone.

### Merge coupling — action required at merge time

`docs/reviews/ME-DAEMON-REVIEW-2026-07-21.md` is cited **4×** in `bin/fleet.py` comments and once
in the substrate row, but it lives on `me/daemon-review`, not `me/daemon` — a deliberate choice,
correctly explained in the commit message, to avoid two branches adding the same path. The
consequence must not be lost: **merging `me/daemon` into `fleet-impl` without `me/daemon-review`
leaves five dangling citations.** Merge both, or neither.

*(Separately: `docs/en/agent-view.md` is also cited and does not resolve — but it was already
dangling at `1015344`. **Pre-existing, not this wave's**, and out of M2's scope. Recorded so the
next reference audit does not re-open it as new.)*

---

## What the next wave must do

One code change, one test inversion, one test addition:

1. `bin/fleet.py:6324` — delete the span gate from the **primary** path. Leave
   `_daemon_wedge_degraded_verdict`'s span check exactly as it is.
2. Invert `test_a_late_burst_of_refusals_passes` → assert `ok is False`, docstring naming what it
   replaced and why (the pattern `test_two_late_refusals_spanning_hours_fail` already sets).
3. Add the case that would have caught this: **the real incident plus one retry 30 s later**,
   asserting `ok is False`.

`DAEMON_WEDGE_MIN_SPAN_SECONDS` stays — the degraded path still needs it. Nothing else in the wave
should be touched; the other eight fixes are sound.
