# Adversarial + spec review — `md/contract` (2.1.212 transient-daemon rehome)

**Reviewer:** fleet worker `md-contract-review` (bg session), 2026-07-17
**Range:** `c1277bd..md/contract` (`aeccd76`, `10c52bf`, `20841b8`, `ea98f20`)
**Machine:** Windows 10 Pro 19045, `claude 2.1.212`, `py -3.13`
**Grep receipts pinned `# at ea98f20`** unless a line says otherwise.

---

## VERDICT: fix-wave

**SPURIOUS-FIX: none.**

**Findings: 5 MAJOR, 5 MINOR, 3 nits.**
**Injections: 5 red / 5 attempted. 2 additional probes stayed GREEN (both are gaps — see M1, N3).**
**Receipts re-run: 8 (of which 6 reproduce verbatim, 2 do NOT reproduce — M2, M3). 1 receipt class unreachable (M4).**

### Why not `merge`

Nothing here is a correctness CRITICAL. I attacked the classifier hard and it is
**fail-safe in every reachable direction**: an unknown third message shape lands
in `failed`, which is behaviourally identical to `daemon-transient` (non-fatal
deferral, husk stays, no event, `removed` uncounted); the tombstone obligation is
committed *before* the rm phase on every stop-shaped path; the "next pass
retries" promise structurally checks out (verified below, not assumed); and the
decision to leave roster reads alone is correct and correctly argued.

But three of the receipts backing a document explicitly staged for **operator
ratification** do not survive re-running (M2, M3, M4), and the fix's own promised
recovery path is unobservable (M1) — a permanently dead daemon starves the husk
tier forever while `fleet doctor` and the `autoclean_run` event both read green.
An operator cannot ratify numbers that are wrong against their own pasted
evidence.

### Why not `reject`

The central reframe is **sound and re-verified**. `claude rm` rc=1 really is
three-way ambiguous and the message really is the only discriminator — R1/R2/R3
below reproduce §Q3 verbatim on this machine. The brief's premise (rm leaves a
roster tombstone) really is refuted, and the builder correctly refused to build on
it. The refusal to implement a "revival nudge" (only a dispatch revives the
daemon; a hygiene pass must not mint a billable session) is the right call, argued
from the right evidence. The roster-read audit's *conclusion* survives even though
its receipt does not.

### Fix wave (ordered)

1. **M1** — surface deferred husks in the autoclean stamp, the `autoclean_run`
   event, and `fleet doctor`.
2. **M2** — re-paste the real §Q4 grep; add the missing `_sweep_husks` row.
3. **M3** — correct `16/16`→`15/15` and `3/3`→`4/4` in both documents.
4. **M4** — tag `RM_TRANSIENT` and the whole `daemon-transient` branch as
   manager-receipt-only, not "verbatim from the live probes".
5. **M5** — either classify `stop` too, or retract the spec claim that every
   `False` caller re-checks the roster.
6. **m1–m5, N1–N3** — as scoped below.

---

## Verification baseline

```
$ PYTHONIOENCODING=utf-8 py -3.13 -m pytest tests/ -q
1075 passed, 6 skipped in 55.37s          # before injections

$ FLEET_LIVE=1 PYTHONIOENCODING=utf-8 py -3.13 -m pytest tests/integration/test_native_pin.py -v
6 passed in 74.54s (0:01:14)              # receipt Q1.4 re-run, on the MODIFIED pin

$ git status --porcelain
(clean)                                   # after every injection was reverted
```

---

# MAJOR findings

## M1 — CRITICAL-adjacent: a permanently dead daemon starves the husk tier **silently**. It surfaces nowhere.

**Severity: MAJOR.** This is the direct answer to the brief's question *"can a
permanently-broken daemon starve hygiene forever silently (where does it surface:
doctor? event? nowhere?)"*. **Nowhere.**

The shipped code (`bin/fleet.py:4871-4877`):

```python
    if deferred:
        # Loud, non-fatal, and honest about the retry: the sweep's own return
        # value counts only what it actually removed, so a caller reporting
        # husks_removed=0 is never mistaken for "nothing to do" (findings §Q2).
        print(f"husk: {len(deferred)} husk(s) left on the roster for the next "
              f"pass: {', '.join(s[:8] for s in deferred)}", file=sys.stderr)
    return removed
```

**The comment asserts the exact opposite of what the code does.** `_sweep_husks`
returns `removed` only; `deferred` is a local that dies at the return. Downstream
(`bin/fleet.py:4961-4996`):

```python
    husks = []
    try:
        husks = _sweep_husks(dry_run, run=run, which=which)
    ...
    summary = {"ts": now_iso(), "dry_run": dry_run, "archive_rc": archive_rc,
               "husks_removed": len(husks), "tombstones_expired": len(tombstones),
               "errors": errors}
    ...
        append_event("autoclean_run", "*", archive_rc=archive_rc,
                     husks_removed=len(husks), ...)
    print(f"autoclean: husks_removed={len(husks)} tombstones_expired={len(tombstones)}"
          f" errors={len(errors)}{' (dry-run)' if dry_run else ''}")
    return 1 if errors else 0
```

A deferral raises no exception, so `errors` stays `[]`. The stamp, the durable
`autoclean_run` event, the printed summary, and the exit code are **byte-identical**
to a clean run with nothing to do: `husks_removed=0 errors=0`, rc=0.

`fleet doctor` then reads that stamp (`bin/fleet.py:5571-5631`) and its own
docstring states the design intent this change defeats:

> LOW advisory (confirmation pass): a fresh timestamp alone can lie — the
> stamp's `errors` array and a lingering fleet.json.corrupt.* artifact (which
> makes tier 2 refuse itself, NEW-1) both mean the sweep is NOT actually doing
> its job. Both are appended to whichever note is returned, so **a bricked sweep
> never reads green-and-fresh**.

A dead-daemon-starved sweep is precisely a bricked sweep, and it is deliberately
kept out of `errors`. Doctor returns `("autoclean", True, "task installed; last
run 0.4h ago")` — green and fresh — forever.

**Failure scenario.** Operator installs `fleet init --autoclean`. Machine goes
quiet; the daemon idle-exits — which §Q2 argues is *the normal state* for a
scheduled autoclean run ("fleet's hygiene tier is the one code path most likely to
meet a dead daemon"). Every hourly pass now defers every husk. The scheduled task
is headless, so the only evidence — the stderr roll-up above — goes to a console
nobody owns. Weeks later the roster has hundreds of fleet-owned husks and their
`~/.claude/jobs/<short>/` dirs. `fleet doctor` has said "task installed; last run
0.3h ago" the entire time. The `autoclean_run` event history records
`husks_removed=0, errors=[]` for every pass — the very "nothing to do" reading the
code comment claims is prevented.

**Injection F (probe) proves it is unpinned:** deleting the entire `if deferred:`
roll-up — the only artifact of the deferral outside a local variable — leaves the
full suite at **1075 passed, 6 skipped**. Nothing in the tree observes it.

**Named fix.** `_sweep_husks` returns `(removed, deferred)` (or stashes deferred
on a caller-visible attribute); `cmd_autoclean` adds `"husks_deferred":
len(deferred)` to both the stamp dict and the `autoclean_run` event, and prints it
in the summary line. **Do not** push it into `errors` — that would flip rc to 1
and turn a routine transient state red, which is exactly the cry-wolf this branch
set out to kill. Then `_doctor_check_autoclean` appends to `extras` when the last
stamp shows `husks_deferred > 0`, matching the shape it already uses for
`run_errors` and the quarantine artifact. Add a unit test asserting the roll-up
count reaches the stamp (Injection F must go red).

---

## M2 — the §Q4 grep receipt does not reproduce, and the audit it backs is incomplete: `_sweep_husks`'s own roster read is missing.

**Severity: MAJOR.** `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md:362-380`
presents this as a pasted receipt:

```
$ grep -n '_fetch_agents_roster(\|"agents", "--json"' bin/fleet.py
2406: ... 2746: ... 2839: ... 2962: ... 3699: ... 3723: ... 3729: ... 4145: ...
4534: ... 5425: ... 6182: ... 6600: ... 6666: ... 6858: ...            # 14 hits
```

Re-run against the base the receipt was taken at:

```
$ git show c1277bd:bin/fleet.py > /tmp/fleet_base.py
$ grep -n '_fetch_agents_roster(\|"agents", "--json"' /tmp/fleet_base.py
2406, 2746, 2839, 2962, 3699, 3723, 3729, 4145, 4534,
4709,          <- MISSING FROM THE RECEIPT
5425, 6182,
6591,          <- MISSING FROM THE RECEIPT
6600, 6666, 6858
$ grep -c ... /tmp/fleet_base.py
16
```

**16 hits, not 14.** The receipt also silently strips the `  # noqa: E731`
suffix from 6182/6858 — it was hand-edited, not pasted.

The two omissions:

- **`4709: roster_ok, payload = _fetch_agents_roster(which=which, run=run)`** —
  this is **`_sweep_husks`'s own roster fetch**: the hygiene tier, the code path
  this very branch rewrote, and the one §Q2 names as *"the code path most likely
  to meet a dead daemon and the least able to revive it"*. It has no row in the
  audit table.
- `6591: def _fetch_agents_roster(...)` — the definition line; harmless, but its
  absence is what proves the block was edited rather than pasted.

The claim this receipt is offered as proof of, in the findings doc
(`:395-397`):

> Every roster read is already behind the epoch-freeze or fails safe. **Zero
> changes made**

and, load-bearing and pending ratification, in `docs/specs/native-substrate.md:43`
(G9 row):

> **[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]** A full audit of **every**
> `claude agents --json` read in `bin/fleet.py` against the idle-exit timeline
> (grep receipt + per-call-site table: §Q4) found **zero reads needing a change**

"A full audit of every read" is false: 14 of 16 were audited.

**Failure scenario.** The operator ratifies G9's amendment on the strength of a
completeness claim. The next contract wave greps the same pattern, gets 16 hits,
finds two with no verdict row, and cannot tell whether they were assessed and
dropped or never seen — which is the exact "untraceable source" failure the
`explore-ui-cli-report.md` note in this same spec exists to prevent. Worse, the
unaudited site is the one the wave modified.

**The conclusion survives; the receipt does not.** I audited `4709` myself: it is
epoch-guarded 120 lines later at `bin/fleet.py:4829` —

```python
    if native_epoch_suspicious(roster_ok, payload, workers):
        raise FleetCliError("husk sweep refused: roster suspicious (G9)")
```

— so its verdict is genuinely "none", same as the rest.

**Named fix.** Re-run the grep, paste the real 16-line output, and add two rows to
the §Q4 table: `4709 | _sweep_husks | epoch-freeze guarded (native_epoch_suspicious
→ FleetCliError, bin/fleet.py:4829) | none` and `6591 | the definition itself |
n/a | none`. Since fleet.py has moved (+144 lines), state the base ref the receipt
was taken at (`c1277bd`) beside the `$` line — the branch's own rule is that grep
receipts are pinned to a ref.

---

## M3 — the `16/16` and `3/3` sample counts are wrong against the doc's own pasted receipt, and are copied into the spec twice.

**Severity: MAJOR.** `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md:299`,
`:328`, `:339`, `:404`, `:473`:

> **Answer: NO. The idle-exit is gated on `live_workers=0` — 16/16 receipts.**
> - **`cause=idle_exit`: 16/16 have `live_workers=0` and `leases=0`.** No counter-example exists in 10 days of history.
> - **`cause=upgrade`: 3/3 shut down WITH live workers** (`live_workers=1`, `1`, and `4`).

Counted from the block **pasted directly beneath those claims**, and re-run against
the live log:

```
$ grep -c "shutting down (cause=idle_exit" ~/.claude/daemon.log
15
$ grep "shutting down (cause=idle_exit" ~/.claude/daemon.log | grep -c "live_workers=0"
15
$ grep -c "shutting down (cause=upgrade" ~/.claude/daemon.log
4
# and inside the doc's own fenced block:
#   idle_exit: 15    upgrade: 4
```

**The truth is 15/15 idle_exit and 4/4 upgrade.** The doc's own receipt lists 19
shutdown lines; the prose miscounts them as 16+3. The `25 daemon starts` figure in
the same sentence is correct (verified: 25).

The miscount is not neutral. The unaccounted 4th upgrade is **line 515**:

```
515: [2026-07-17T00:35:25.950Z] [supervisor] shutting down (cause=upgrade, uptime=37086s, leases=2, live_workers=1)
```

The doc enumerates the upgrade sample as `(live_workers=1, 1, and 4)` — three
values — while 515 (`live_workers=1`) is in its own pasted block. And 515 is
**the very shutdown whose aftermath the doc quotes twice as the residual G9
hazard**:

```
[2026-07-17T00:35:29.135Z] bg adopt: adopted=1 respawned=0 dead=0
[2026-07-17T00:35:44.160Z] bg: post-takeover prewarm burst — respawned 0/1 stale workers, 1 refused in 0s
```

So the doc excludes an event from its denominator while citing that same event's
consequence as the finding. The direction of both errors compounds: it overstates
the reassuring sample (idle_exit) by one and understates the hazard sample
(upgrade) by one.

These figures are then copied verbatim into the ratification target,
`docs/specs/native-substrate.md`, twice:

- `:43` (G9 row): *"carries **`leases=0, live_workers=0`** — 16/16, no counter-example"*
- `:209`: *"An idle-exit is gated on `live_workers=0` (16/16 receipts)"*
- `:231`: *"**The `cause=upgrade` shutdown path** (3/3 shut down with live workers...)"*

**Failure scenario.** The operator ratifies G9's idle-exit half on "16/16, no
counter-example", then re-derives the count from the log during a later wave, gets
15, and cannot tell whether a line was lost, the log rotated, or the author
miscounted — so the amendment's credibility, and every downstream decision built
on "no roster read needs to change", is back in question over arithmetic. The
`3/3` error is worse in kind: it undercounts the one hazard the doc says is real.

**The verdict is unaffected** — 15/15 is still no counter-example, and 4/4 upgrade
shutdowns still carry live workers. Only the numbers are wrong.

**Named fix.** `16/16` → `15/15` at findings `:299`, `:328`, `:404`, `:473` and
spec `:43`, `:209`. `3/3` → `4/4` at findings `:339`, `:473` and spec `:231`, and
correct the enumeration to `(live_workers=1, 1, 4, 1)`. Add the count commands
themselves as receipts so the next reader re-derives instead of re-counting by eye.

---

## M4 — the entire `daemon-transient` branch rests on a string **no one in this evidence chain has observed**, and the test file misrepresents its provenance.

**Severity: MAJOR.** `tests/test_native_daemon_transient.py:1-8` (module docstring):

> these are unit tests over injected `run` stubs whose stdout/stderr/returncode
> are copied **VERBATIM from the live probes**, so the taxonomy stays pinned
> without a live daemon.

That is true of `RM_OK`, `RM_GONE`, `STOP_GONE` (I re-ran all three — R1/R2/R3
below, byte-identical). It is **false of the one stub that matters**:

```python
RM_TRANSIENT = types.SimpleNamespace(
    returncode=1,
    stdout="",
    stderr="couldn't remove aaaa1111 — the background service may be "
           "restarting. Try again in a moment.")
```

There was no live probe. The same branch's findings doc says so explicitly
(`§Q2:198`): *"**Answer: BLOCKED (containment)** … The dead-daemon state is
**unreachable from this worker**"*, and the hazard note it wrote into the spec
generalises the reason:

> **Corollary for every observer:** a fleet process running *inside* a `--bg`
> session … always sees a live daemon and therefore **cannot reproduce the
> dead-daemon path at all**

**That corollary binds me too.** I am a `--bg` session (`claude daemon status`
confirms `origin: transient — started on-demand by \`claude --bg\`` with 3 bg
workers holding it open — R8), and reaching the dead-daemon state requires either
`claude daemon stop` (banned, machine-wide blast radius) or ending sessions I do
not own. **So the dead-daemon receipts are unreachable for me too, and I did not
re-run them.** The transient message's exact text is second-hand from the manager
in both this branch's evidence and mine.

The tell that nobody had the bytes: the same message is transcribed with **two
different dashes** in the same commit —

- `bin/fleet.py:4414` (comment): `couldn't remove <id> - the background service may be restarting.`  ← ASCII hyphen
- `tests/test_native_daemon_transient.py:38` (the "verbatim" stub): `couldn't remove aaaa1111 — the background service …`  ← em-dash
- findings `:285` / spec `:146`: `— the background service …`  ← em-dash

Three transcriptions, two dashes. A verbatim capture cannot disagree with itself.

**Failure scenario.** A reader (or the operator at ratification) takes the "copied
VERBATIM from the live probes" docstring at face value, treats the transient
taxonomy as pinned-to-observation like the other two rows, and ratifies G12's
dead-daemon bullet as evidenced. It is evidenced only by a manager report the
branch never reproduced — the same standard the branch (correctly, admirably)
refuses to accept for its own claims. The whole point of §Q2's BLOCKED discipline
is lost the moment the test file relabels the result as a live probe.

**Mitigation, stated fairly.** The blast radius is small, because the design is
fail-safe here by accident of structure: `_NATIVE_CLI_TRANSIENT_RE` matches only
the middle phrase `background service may be restarting`, which is dash-agnostic
and survives the wording drift around it; and an unmatched third shape falls to
`failed`, whose behaviour is identical to `daemon-transient` in every respect that
touches state (`ok=False`, no `husk_removed` event, not counted in `removed`,
non-fatal deferral). Only the operator-facing note text differs
(`_rm_outcome_note`: *"unknown rm failure"* vs the retryable gloss). So a
locale/wording drift degrades diagnosis, never correctness. **This is the single
best property of the change and it should be stated in the code, not left to be
rediscovered by a reviewer.**

**Named fix.** (a) Retitle the module docstring: stubs are verbatim *except*
`RM_TRANSIENT`. (b) Tag the stub inline: `# [MANAGER RECEIPT — NOT RE-OBSERVED:
the dead-daemon state is unreachable from a --bg session (findings §Q2). Two
independent reviewers have now failed to reach it. The regex deliberately matches
only the dash-free middle phrase for this reason.]` (c) Add a test that pins the
fail-safe property itself — assert `_rm_native_session_status` returns
`(False, ...)` and `_sweep_husks` emits no `husk_removed` for a *third* unknown
shape — so the "unknown degrades to a safe deferral" guarantee is contract, not
coincidence. (d) Add to the spec's "Open, for the operator" list: *the transient
message text is unverified by two waves; capture it during the standalone G9 probe
on a quiet machine.*

---

## M5 — the commit says "rm/stop"; `stop` was never classified. The spec's stated justification for that is **false at 2 of 5 call sites**.

**Severity: MAJOR.**

```
$ git log --oneline -1 10c52bf
10c52bf fix(native): classify claude rm/stop outcomes by message, not exit code
```

`_stop_native_session` is untouched by the diff and still classifies by exit code
alone (`bin/fleet.py:5974-5976`):

```python
        if proc.returncode == 0:
            return True
    return False
```

The only thing `stop` got was a classifier test (`test_stop_gone_message_variant_also_classifies_gone`)
that exercises `_classify_native_cli_result` directly — **no `stop` code path calls
it**. The commit subject over-claims.

That is defensible on its own; the spec's justification for it is not.
`docs/specs/native-substrate.md:150`, tagged PENDING OPERATOR RATIFICATION:

> Fleet deliberately leaves `_stop_native_session`'s bool semantics unchanged
> (False = "could not verify" ⇒ **callers re-check the roster, which is fail-safe**).

Re-run receipt R2 proves an already-gone id returns `False` from `stop`:

```
$ claude stop deadbeef
No job matching 'deadbeef'. Run 'claude agents' to list running sessions.
rc=1
```

Call sites (`# at ea98f20`):

```
$ grep -n "_stop_native_session(" bin/fleet.py
3547:    stopped_ok = _stop_native_session(sid, run=run, which=which)
3714:        stopped_ok = _stop_native_session(old_sid, run=run, which=which)
3937:    stopped_ok = _stop_native_session(sid, run=run, which=which) if sid else True
3948:        ok = _stop_native_session(retired, run=run, which=which, timeout=...)
6396:        stopped = _stop_native_session(sid, run=run, which=which, timeout=...)
```

`3714` (`cmd_respawn --force`) and `6396` (`_cleanup_wedged`) do re-check the
roster — the claim holds there. **`3937` and `3948`, both in `_cmd_kill_native`,
do not re-check anything** (`bin/fleet.py:3937-3971`):

```python
    stopped_ok = _stop_native_session(sid, run=run, which=which) if sid else True
    ...
    for retired in retired_sids:
        ...
        ok = _stop_native_session(retired, run=run, which=which,
                                  timeout=_RETIRED_SID_SWEEP_TIMEOUT_SECONDS)
        print(f"fleet: {name}: stopping retired session {retired[:8]}... "
              f"{'ok' if ok else 'timeout'}", file=sys.stderr)
    ...
        append_event("killed", name, interrupt_outcome=stopped_ok)

    if not stopped_ok:
        print(
            f"fleet: {name}: claude stop could not be verified -- marked dead anyway "
            "(kill is a terminal action); investigate the session manually",
            file=sys.stderr,
        )
        return 1
```

Three defects, all of them the **exact cry-wolf this branch cured on `rm` and left
standing on `stop`**:

1. **`3950`: `'ok' if ok else 'timeout'`.** An already-gone retired sid — the
   overwhelmingly common case, since retired sids are abandoned forks — prints
   `timeout`. Not "failed", not "unknown": a *specific and wrong diagnosis*
   naming a mechanism that did not occur. Findings §Q3 puts the same defect on rm
   at the top of its table (*"an already-clean sid is reported to the operator as
   `rm ... failed`"*) and fixes it. Here it is worse, because "timeout" invites
   the operator to go looking for a hung daemon.
2. **`3969`: `return 1`.** `fleet kill` on a worker whose session is already off
   the roster exits **1** and prints *"investigate the session manually"* about a
   session that is verifiably, correctly gone. Any script or scheduler wrapping
   `fleet kill` reads that as a failed kill.
3. **`3961`: `append_event("killed", name, interrupt_outcome=stopped_ok)`** writes
   `interrupt_outcome=False` — a **wrong datum in the durable event log**, not
   just a console message. Every consumer of that event now believes the stop
   failed.

None of this is fail-*unsafe* (the tombstone is written at `3952-3953` regardless,
and the worker is marked dead regardless — G9's never-assume-dead doctrine is
preserved, correctly). It is a cry-wolf and a data-quality defect, in the one
verb the commit subject claims to have fixed.

**Failure scenario.** Operator archives a worker (rm removes its roster entry —
now correctly reported as `gone`), then runs `fleet kill` on the stale record.
Kill exits 1, tells them to investigate a session that does not exist, and stamps
`interrupt_outcome=False` forever. The rm half of the same command prints a clean
`gone`. The two halves of one contract now disagree about the same fact.

**Named fix.** Preferred: `_stop_native_session_status(sid, ...) -> (ok, outcome)`
reusing `_classify_native_cli_result` verbatim (the classifier is already
stop-aware — `test_stop_gone_message_variant_also_classifies_gone` proves it
handles stop's extra hint sentence), with `_stop_native_session` kept as its bool
face exactly like `_rm_native_session`. Then `_cmd_kill_native` treats `gone` as
success (rc 0, `interrupt_outcome=True`), and `3950` prints the outcome instead of
guessing `timeout`. Minimum acceptable: strike the "callers re-check the roster"
claim from the spec, name the two call sites that don't, and fix `'timeout'` →
`'failed'`. Either way the commit subject should say `rm` if only rm is classified.

---

# MINOR findings

## m1 — `gone` short-circuits the full-sid retry: the one fail-**unsafe** direction in the change.

**Severity: MINOR** (needs CLI drift to fire — but CLI drift is this branch's
entire reason to exist; this is the 8th live catch).

`bin/fleet.py:4469-4483`:

```python
    refs = dict.fromkeys((_native_job_ref(sid), sid))
    outcome = "failed"
    for ref in refs:
        ...
        outcome = _classify_native_cli_result(proc)
        if outcome in ("ok", "gone"):
            return (True, outcome)
        if outcome == "daemon-transient":
            return (False, outcome)
    return (False, outcome)
```

The `gone` inference — *"the sid ALREADY reached the desired end state"* — is
sound **only if the ref was right**. The ref is derived, not read:
`_native_job_ref(sid)` returns `sid.split("-", 1)[0]`. Every call site has the
roster entry in hand, carrying the CLI's **own** `id` field (`{"id": "0a208ce0",
..., "sessionId": "0a208ce0-6b76-..."}`), and uses the derived string instead.

The retry exists precisely to cover a ref that the CLI rejects. Its own docstring
says so: *"belt-and-braces against a **future CLI accepting full ids**"*. The
short-circuit removes it on the exact path where a ref mismatch manifests — a
rejected ref reports `No job matching`, which is now read as success.

**Failure scenario.** A future CLI stops accepting the bare 8-char prefix (or
lengthens the short id) but accepts the full sid. `_sweep_husks` calls rm with the
derived short ref → `No job matching '<short>'` → **`gone` → `ok=True` →
`append_event("husk_removed", ...)` → `removed.append(sid)`** → `autoclean:
husks_removed=1`. The session, its roster entry, and its `~/.claude/jobs/<short>/`
dir are all still there, and fleet has recorded a durable event saying it removed
them — while the full-sid ref that *would* have worked was never tried. Pre-fix,
this same drift returned `False` and printed `husk: rm <sid> FAILED -- left in
place` on every pass until someone looked.

Every other branch of this change fails safe. This one converts a failure into a
**silent claimed success plus a false event** — the one outcome the classifier's
own docstring says must never happen (*"a retryable failure must never be
downgraded to 'already clean' — that would silently claim success for a husk that
is still on the roster"*). The reasoning is right; it just wasn't applied to
`gone`.

**Note the tension the fix must resolve:** `test_gone_short_circuits_the_full_sid_retry`
pins the short-circuit *as contract*, so it is not a free change.

**Named fix.** Kill the mismatch class at the source rather than restoring the
retry (which costs a doomed subprocess per already-clean sid per pass — the thing
the pin was written to prevent): pass the roster entry's own `id` at the two
hygiene call sites, e.g. `_rm_native_session_status(sid, ref=entry.get("id"))`,
falling back to `_native_job_ref(sid)` when the entry has no usable `id`. The
`gone` verdict then rests on the CLI's own identifier and the short-circuit stays
honest. If the retry is restored instead, amend
`test_gone_short_circuits_the_full_sid_retry` in the same commit and say why.

## m2 — the pin's `_daemon_alive()` **samples** the confound; it does not control it. Fleet's own verdict was available and discarded.

**Severity: MINOR.**

`tests/integration/test_native_pin.py` (test 5) runs the archive, reads the
roster, and only then probes the daemon:

```python
    leftover = {s: e for s, e in leftover.items() if e is not None}
    alive, status_text = _daemon_alive()
    if leftover and alive is False:
        pytest.skip("ACHIEVABLE-CONTRACT SKIP [2.1.212, PENDING-RATIFICATION]: ...")
```

The brief asks whether this controls the confound or asserts around it. **It
asserts around it, one probe too late, and it is racy in both directions:**

- **False skip (masks a real regression).** The daemon idle-exits **~5s** after
  the last client disconnects. Test 5's own flow stops every worker, waits for
  gone-or-dead, archives, then fetches the roster — comfortably more than 5s of
  zero-live-workers. So the daemon can be **alive during rm** (rm works, roster
  should be clean) and **dead by the sample**. If a genuine contract regression
  leaves an entry behind in that window, `alive is False` converts the RED into a
  skip — the suite reports success for the exact break it exists to catch.
- **False RED.** Daemon dead at rm, then a sibling worker or another operator
  dispatches (the only thing that revives it) before the sample → `alive is True`
  → hard assert → "a genuine contract regression, not the daemon-lifecycle
  confound". On a machine where the findings doc itself documents 3 concurrent
  M-D siblings, this is not hypothetical.

Meanwhile **fleet already knows the answer at rm time**. `_rm_native_session_status`
classified the outcome from the CLI's own message in the same process, and
`_archive_move_and_rm` printed it verbatim: `fleet: <n>: rm <s>... deferred
(daemon-transient) -- the background daemon is down/restarting …`. That is the
direct, race-free signal, and the pin throws it away in favour of an independent,
later, weaker probe of the same variable.

The suite is nonetheless a real improvement over the silent dependency it
replaces, and `alive is None` correctly hard-asserts rather than skipping. This is
a strengthening, not a rejection.

**Named fix.** Capture the archive command's stderr (test 5 already invokes it)
and branch on fleet's own classification: `deferred (daemon-transient)` present →
skip; absent → assert. Keep `_daemon_alive()` for the diagnostic paste (which is
genuinely valuable — it is what makes a future RED self-explaining) and as the
fallback when the archive path emitted no classification line at all.

## m3 — G12's action column now contradicts its own amendment, three lines apart.

**Severity: MINOR.** `docs/specs/native-substrate.md:46`, consequence column. The
amendment states:

> • **Live-session behavior — OBSERVED** (was "UNOBSERVED and out of contract") …
> • **Idempotency — REFUTED IN FORM, held in effect** (was UNOBSERVED)

and the original text in the **same cell**, immediately above it, still reads:

> Confirmed as the archival primitive for spec §5.1.2 (auto-archival). UNOBSERVED
> and out of contract: behavior against a *live* session (force-stop-first vs.
> refuse — untested); **idempotency against an already-removed id**; whether `rm`
> also clears the transcript file under `~/.claude/projects/`.

The no-self-ratification rule correctly forbids **changing the verdict**. It does
not require leaving a refuted claim standing as live guidance in the operative
column — and the consequence column is the one a reader acts on. Note the third
item (transcript clearing) is still genuinely UNOBSERVED and the amendment says so;
only the first two are stale.

**Failure scenario.** An implementer reads G12's consequence column, sees
"UNOBSERVED and out of contract: behavior against a *live* session", and adds a
defensive stop-before-rm — re-introducing exactly the ordering the amendment
retired, and burning a wave to rediscover §Q1.2.

**Named fix.** Annotate without touching the verdict: `~~behavior against a *live*
session~~ [SUPERSEDED by the 2.1.212 amendment in this cell — OBSERVED, §Q1.2]`
and the same for idempotency. The status stays `CONFIRMED`; nothing is
self-ratified; the stale guidance stops being actionable.

## m4 — `test_transient_rm_reports_retryable_and_still_archives` does not test "still archives".

**Severity: MINOR.** `tests/test_native_daemon_transient.py:231-242`:

```python
    def test_transient_rm_reports_retryable_and_still_archives(self, home, capsys):
        """Archive commits the tombstone BEFORE the rm phase by design, so a
        dead daemon must not undo the archive -- but it must not be reported
        as a plain failure either: ..."""
        dest = home / "logs" / "archive" / "w1"
        fleet._archive_move_and_rm("w1", SID, [], dest, ...)
        err = capsys.readouterr().err
        assert "daemon" in err.lower() and "retr" in err.lower(), err
```

`dest` is bound and never asserted on. The test name and docstring both claim the
archive survives; the body only checks two substrings of stderr. The property is
real — I verified the ordering by hand (`cmd_archive` stamps `archived_at`,
`save_registry`, and `append_event("archived", ...)` **before** calling
`_archive_move_and_rm`, `bin/fleet.py:4667-4674`) — but it is unpinned, and a test
named for a property it does not check is worse than no test: it reads as coverage.

**Failure scenario.** A future refactor moves the rm phase ahead of the
`archived_at` commit (or makes a transient rm abort the archive). This test stays
green, because stderr still says "daemon"/"retr". The tombstone obligation — the
thing G10 makes mandatory — breaks silently.

**Named fix.** Assert the archive actually happened: `assert dest.exists() and
any(dest.iterdir())`, matching `test_5_pin_archive_rm`'s own
`archive did not move any files into {dest}` check. Or rename the test to
`test_transient_rm_is_reported_as_retryable` and pin the ordering separately.

## m5 — `_rm_native_session_status`'s docstring cites §Q3 for a claim §Q3 does not make.

**Severity: MINOR.** `bin/fleet.py:4462`:

> 2.1.212 [PENDING-RATIFICATION]: the two message-classified outcomes
> short-circuit that retry — **findings §Q3 confirms** the full-uuid call returns
> the same "No job matching", and **a dead daemon rejects both refs identically**,
> so retrying only doubles the stall …

The first half is a real receipt (§Q3, re-run as R3 below — confirmed). The second
half — "a dead daemon rejects both refs identically" — **has no receipt anywhere**:
the dead-daemon state was unreachable (§Q2), so no one has ever run rm against a
dead daemon with *either* ref, let alone both. It is a reasonable inference (a
daemon that cannot answer cannot discriminate refs) presented inside a sentence
whose subject is "findings §Q3 confirms".

The conclusion is almost certainly right and the consequence is benign (it halves
a doomed stall). But this is the same evidence-hygiene the branch enforces
everywhere else, and it is the one place it slipped — inside the docstring of the
function the whole commit is named for.

**Named fix.** Split the sentence: *"§Q3 confirms the full-uuid call returns the
same `No job matching` (receipt). The transient short-circuit is **reasoning, not
a receipt** — a daemon that cannot answer cannot discriminate refs; the
dead-daemon state is unreachable from a bg session (§Q2), so this is untested."*

---

# Nits

- **N1** — findings `:469` (summary item 5): *"On a live session: `rc=1`→`rc=0`
  `stopped <id>`"*. The `rc=1`→ is spurious; receipt §Q1.3 shows `rc=0` on the
  first call. Reads as a documented retry that does not exist.
- **N2** — `bin/fleet.py:4414` transcribes the transient message with an ASCII
  hyphen while every other copy uses an em-dash (see M4). Harmless — the regex
  spans neither — but pick one.
- **N3 (probe G, stayed green)** — `_rm_outcome_note`'s `no-claude` / `error`
  strings are unpinned: replacing both with `"XXX"` leaves the full suite at
  **1075 passed, 6 skipped**. Only the `daemon-transient` gloss is asserted
  (via `"daemon"`/`"retr"` substrings). Low stakes — these are console strings on
  paths that already fail loudly — but if the retryable gloss is worth pinning,
  so is "claude not on PATH".

---

# Injection table

Every injection applied to `bin/fleet.py`, reverted with `git checkout --
bin/fleet.py` immediately after. Targeted runs against
`tests/test_native_daemon_transient.py tests/test_native.py::TestCmdArchive`
(34 tests); probes against the full `tests/` suite. **Final `git status`:
clean.**

| # | path broken | how | result | test(s) that went red |
|---|---|---|---|---|
| A | `_NATIVE_CLI_TRANSIENT_RE` | regex → `zzz-never-matches-zzz` (wording drift) | 🔴 **6 failed**, 28 passed | `test_may_be_restarting_is_daemon_transient`, `test_transient_wins_over_gone_if_both_appear`, `test_daemon_transient_is_not_success`, `test_transient_does_not_retry_with_full_sid`, `TestHuskSweepAgainstDeadDaemon::test_transient_husk_is_deferred_loudly_not_removed`, `TestArchiveRmAgainstDeadDaemon::test_transient_rm_reports_retryable_and_still_archives` |
| B | `_NATIVE_CLI_GONE_RE` | regex → `zzz-never-matches-zzz` (wording drift) | 🔴 **7 failed**, 27 passed | `test_no_job_matching_is_gone_not_failed`, `test_stop_gone_message_variant_also_classifies_gone`, `test_gone_counts_as_success`, `test_gone_short_circuits_the_full_sid_retry`, `test_bool_wrapper_keeps_its_contract`, `test_already_gone_husk_counts_as_removed`, `test_already_gone_rm_is_reported_as_ok_not_failed` |
| C | classifier tie-break order | `gone` checked before `daemon-transient` | 🔴 **1 failed**, 33 passed | `test_transient_wins_over_gone_if_both_appear` |
| D | transient retry short-circuit | deleted `if outcome == "daemon-transient": return (False, outcome)` | 🔴 **1 failed**, 33 passed | `test_transient_does_not_retry_with_full_sid` |
| E | rc=0 fast path | deleted `if proc.returncode == 0: return "ok"` (rc=0-with-error shape) | 🔴 **4 failed**, 30 passed | `test_zero_exit_is_ok`, `test_ok`, `test_claude_missing_is_not_a_crash`, `test_bool_wrapper_keeps_its_contract` |
| **F** | **`_sweep_husks` deferred roll-up** | **deleted the entire `if deferred:` block — the only artifact of a deferral outside a local** | 🟢 **1075 passed, 6 skipped — STAYED GREEN** | **none → M1** |
| **G** | **`_rm_outcome_note`** | **`no-claude` / `error` glosses → `"XXX"`** | 🟢 **1075 passed, 6 skipped — STAYED GREEN** | **none → N3** |

**A–E: 5 red / 5 attempted.** The classifier core is genuinely well pinned — the
tie-break order, the retry short-circuits, and both regexes each have a dedicated
test that dies when broken. Injection A is the most reassuring result in this
review: a locale/wording drift on the transient message is caught by six tests,
and (per M4) even an *uncaught* drift degrades only the operator note, never the
state transition.

**F and G are the gaps.** F is not a missing test — it is a missing *feature*
(M1): the deferral has no observable outside a stderr line no scheduled task
captures, so there is nothing for a test to bind to.

---

# Receipts re-run

Verbatim, this session, on `claude 2.1.212` (`$ claude --version` → `2.1.212
(Claude Code)`).

| # | receipt | source | result |
|---|---|---|---|
| **R1** | `claude rm deadbeef` | §Q3 | ✅ **reproduces** — `No job matching 'deadbeef'` / `rc=1` |
| **R2** | `claude stop deadbeef` | §Q3 | ✅ **reproduces** — `No job matching 'deadbeef'. Run 'claude agents' to list running sessions.` / `rc=1` (byte-identical, incl. the hint sentence `STOP_GONE` pins) |
| **R3** | `claude rm 0a208ce0-6b76-41c1-85e6-751c85306d13` (full uuid) | §Q3 | ✅ **reproduces** — `No job matching '<full-uuid>'` / `rc=1`. The full-sid-retry-is-pointless claim is real. |
| **R4** | `claude daemon --help` service-install line | "lifecycle rule" | ✅ **reproduces** verbatim — *"Service install is disabled in this version — the daemon runs on demand and exits when the last client disconnects."* |
| **R5** | `FLEET_LIVE=1 pytest tests/integration/test_native_pin.py -v` | §Q1.4 | ✅ **6 passed in 74.54s** — on the **modified** pin. (§Q1.4's "6/6 unmodified" was pre-change; this re-run confirms the new `_daemon_alive()` gate and the rm-taxonomy assertion run live and green.) |
| **R6** | `grep -n "shutting down" ~/.claude/daemon.log` | §Q4 | ⚠️ **lines reproduce, counts do not** → **M3**. Same 19 lines, same line numbers (17…553). But `idle_exit` = **15**, not 16; `upgrade` = **4**, not 3. (`25 daemon starts` ✅ correct.) |
| **R7** | `grep -n '_fetch_agents_roster(\|"agents", "--json"' bin/fleet.py` @ `c1277bd` | §Q4 | ❌ **does not reproduce** → **M2**. Real output: **16 hits**; the doc pastes **14** (missing `4709` = `_sweep_husks`, and `6591` = the def), with `# noqa: E731` stripped from two lines. |
| **R8** | `claude daemon status` | "lifecycle rule" | ✅ **reproduces the structure** — `origin: transient — started on-demand by \`claude --bg\``, 3 bg workers holding it open. Confirms the observability corollary **binds this reviewer too** (see M4). |

## Receipts I could **not** re-run — stated, not trusted silently

**Every dead-daemon receipt (§Q2, §Q3's transient row, spec `:146`'s hazard note,
G12's dead-daemon bullet).** I am a `--bg` session (R8), so the daemon cannot
idle-exit while I run. Reaching that state requires `claude daemon stop` (banned:
machine-wide blast radius, terminates sessions I do not own) or ending every bg
session on the machine (three M-D siblings that are not mine to end). Per the
brief, I record this rather than trusting it:

- **`couldn't remove <id> — the background service may be restarting. Try again
  in a moment.`** — the exact string, rc, and stream (stdout vs stderr) are
  **unverified by two independent waves now**. It is a manager report. Everything
  downstream — `_NATIVE_CLI_TRANSIENT_RE`, `RM_TRANSIENT`, the pin's skip branch,
  G12's dead-daemon bullet — inherits that provenance. See **M4**.
- **"rm does not revive the daemon; only a dispatch does."** Unverified here.
  Load-bearing for the entire "loud non-fatal deferral" design.
- **"With a dead daemon, `claude agents --json [--all]` still answers from the
  on-disk snapshot."** Unverified here. Load-bearing for the husk tier's ability
  to even *see* the husks it defers.

The builder was **honest and correct** to mark §Q2 BLOCKED rather than reach for
`claude daemon stop`, and correct to refuse `claude daemon run` on takeover
grounds — the `bg adopt` / `1 refused` log lines make that risk concrete, and I
reached the same conclusion independently. The defect is not the gap; it is that
`tests/test_native_daemon_transient.py`'s docstring relabels the gap as a live
probe (M4).

---

# SPURIOUS-FIX: none

The brief's tombstone-relaxation premise (*"rm leaves the sid in `--all`"*) was
refuted by §Q1 and **no residue of it landed**. Checked explicitly:

- **The pin's roster-gone assertion was not relaxed on the refuted ground.** With
  a live daemon it still hard-asserts, and the new comment says so in as many
  words: *"The brief's premise that rm leaves an `--all` tombstone behind is
  REFUTED; no relaxation of the roster-gone assertion is warranted on that
  ground."* The only relaxation (`pytest.skip`) is gated on `alive is False` — a
  different, separately-evidenced condition. `alive is None` still hard-asserts.
  (Its *implementation* is racy — m2 — but that is a soundness bug in the gate,
  not premise residue.)
- **`_stop_native_session` was left alone** — no speculative rework (M5 argues it
  was left *too* alone, which is the opposite of spurious).
- **Roster reads: zero changes**, explicitly on G9 doctrine (*"Nothing was 'fixed'
  here on suspicion"*). I re-ran the audit grep myself (R7): the receipt is
  incomplete (M2), but the *verdict* — every read epoch-guarded or fail-safe — is
  correct, including the `4709` site the table omits (guarded at
  `bin/fleet.py:4829`).
- **The `gone`→success change is not spurious**: R1/R3 prove pre-fix `rm` reported
  every already-clean sid as `failed`. Real defect, real fix.
- **The `daemon-transient` branch is not spurious either** — it rests on thin
  evidence (M4), but "thinly evidenced" ≠ "fixing what was never broken", and its
  unknown-shape fallback is fail-safe regardless.

# Doctrine checks (lens (a))

| obligation | verdict |
|---|---|
| Every G-row amendment tagged `[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]` | ✅ 9/9 tags carry the full phrase; 0 bare `[OBSERVED 2.1.212]`. |
| No self-ratification — every Status/verdict line vs `git diff c1277bd..md/contract` | ✅ **clean.** The diff touches only G9 and G12; both verdicts (`DEFERRED-proposed`, `CONFIRMED`) are byte-identical pre/post. Amendments are appended, never substituted. G9 explicitly stays DEFERRED *as a gate* while answering its idle-exit half. Exemplary. |
| G9 never-assume-dead doctrine preserved in `bin/fleet.py` | ✅ No new liveness inference. `daemon-transient`/`failed` → husk **stays**; `_sweep_husks` still refuses on `native_epoch_suspicious` (`:4829`) and still skips any entry with `status`/`pid` (`:4846`). |
| Tombstone obligation intact on every stop-shaped path | ✅ `cmd_archive` stamps `archived_at` + `append_event("archived")` **before** `_archive_move_and_rm` (`:4667-4674`), so a deferred rm cannot undo it. `_cmd_kill_native` writes `write_tombstone_outcome(name, sid, "killed")` (`:3953`) and marks dead regardless of `stopped_ok`. No rm/stop outcome gates a tombstone. (Unpinned in the new tests — m4.) |
| "The autoclean husk tier retries it" — **verified, not assumed** | ✅ **holds.** `_registry_owned_and_protected_sids` (`:4714`) puts archived records' sids in `owned` but **not** `protected` (`if rec.get("archived_at") is None: protected.update(sids)`), and `owned` is further widened by `_archive_dir_sids()` + `_events_sids()`. A deferred sid is a no-`status`/no-`pid` entry, so it clears the live gate. The husk tier really can sweep it next pass. (It just cannot tell anyone it hasn't — M1.) |

---

## Bottom line

The reasoning is the strongest part of this branch. Refusing to build on the
brief's refuted premise, refusing to mint a billable session as a hygiene side
effect, refusing to touch roster reads the evidence clears, refusing `claude
daemon stop` and `daemon run` on containment grounds, and appending rather than
substituting every G-row verdict — that is five hard calls in a row, made
correctly, and the fix-wave below does not touch any of them.

What needs fixing is the bookkeeping around it: a deferral nobody can see (M1),
two receipts that do not reproduce (M2, M3), a stub labelled as observed when it
is reported (M4), and a commit that says `stop` when it means `rm` (M5).

`VERDICT: fix-wave(M1, M2, M3, M4, M5, m1, m2, m3, m4, m5, N1, N2, N3)`
`SPURIOUS-FIX: none`

---
---

# RE-REVIEW — 2026-07-17 (wave 2)

**Reviewer:** fleet worker `md-contract-review` (bg session)
**Range:** `a71e7c4..e2ee7c5` — `eda3328` (fix: surface starved husk sweeps; classify stop; rm by roster id), `1407757` (test: branch on fleet's own rm classification), `e2ee7c5` (docs: correct the receipts; disposition table)
**Machine:** Windows 10 Pro 19045, `claude 2.1.212`, `py -3.13`
**Grep receipts pinned `# at e2ee7c5`** unless a line says otherwise.

## RE-REVIEW VERDICT: fix-wave(ND-1, ND-2, ND-3)

**All 13 findings FIXED. 0 NOT-FIXED, 0 REGRESSED, 0 SPURIOUS-FIX.**
**3 new defects, all introduced by the fix wave itself: 1 MAJOR, 2 MINOR. 1 nit.**
**Injections: 12 / 12 red** (my original 5, my 2 wave-1 green probes — both now red — and 5 new ones against the new code).
**Suite: 1097 passed / 6 skipped** (was 1075; +22 tests) before and after every injection. **FLEET_LIVE pin: 6/6 green** (69.04s). **Tree clean.**

This is a good fix wave. Every finding was fixed *as named*, each one is now pinned
by a test that dies when the fix is reverted, and the two gaps I could only
demonstrate by deleting code (Injections F and G) are the two the builder bound
tests to first. The corrections to the findings doc go further than I asked: the
count commands are now receipts in their own right, and the unverified-claim list
became a numbered operator item. Nothing was fixed that was not broken.

The three new defects are all the same shape, and it is the shape the brief
predicted: **a fix applied at one call site and not at its twin.** ND-1 is the
serious one — `m1`'s hardening went to both `rm` call sites and neither `stop` call
site, in the commit that gave `stop` the very inference `m1` exists to make safe. I
have a working repro.

### Fix wave (ordered)

1. **ND-1** (MAJOR) — pass `ref=rec.get("native_short_id")` at `_cmd_kill_native`'s stop call.
2. **ND-2** (MINOR) — implement the `_daemon_alive()` fallback the pin's comment promises.
3. **ND-3** (MINOR) — threshold the doctor note on a streak, not on the first deferral.
4. **n1** (nit) — one line of the re-pasted §Q4 receipt is still hand-edited.

---

## Disposition of the wave-1 findings

| # | finding | disposition | evidence |
|---|---|---|---|
| **M1** | starved sweep surfaces nowhere | **FIXED** | `_sweep_husks` → `(removed, deferred)`; `husks_deferred` rides the stamp (`:5051`), the `autoclean_run` event (`:5063`) and the summary line; `_doctor_check_autoclean` appends the note (`:5685`). Note-only, `errors` untouched, rc still 0 — exactly as named, and `test_deferral_is_not_an_error_and_does_not_flip_rc` pins the restraint. Injection F (wave 1: **green**) and new Injections F2/K now red. **See ND-3 for the threshold.** |
| **M2** | §Q4 grep receipt hand-edited: 14 of 16 hits, `_sweep_husks` omitted | **FIXED** | Re-ran at the base ref: 16 hits. The doc now pastes 16, pinned to `c1277bd`, `# noqa: E731` restored; the audit table gained a bolded **4709** row (`_sweep_husks`, epoch-guarded, verdict "none" — matching my own independent audit) and a `6591` row. **See nit n1.** |
| **M3** | `16/16`/`3/3` miscounted | **FIXED** | Re-derived every figure against the live log: `idle_exit`=**15**, of which `live_workers=0`=**15**; `upgrade`=**4** (`1 1 4 1`); `shutting down`=**19**; `daemon start`=**25**. All six match the doc. The count commands are now receipts, and the corrected prose names line 515 as the dropped upgrade whose aftermath it quotes. |
| **M4** | `RM_TRANSIENT` provenance overstated | **FIXED, and then some** | Module docstring split by stub; `RM_TRANSIENT` tagged `[OBSERVED interactive 2026-07-17 manager session — NOT RE-OBSERVED HERE]`; the em-dash labelled a transcription choice, not evidence. My requested (c) landed as `TestUnknownMessageShapeFailsSafe` — the fail-safe guarantee is now contract, not an accident of structure — plus `test_transient_matches_regardless_of_dash_style` (5 dash styles) and `test_stream_and_case_do_not_matter`. My requested (d) landed as spec operator item **5**, which correctly generalises to the two other unverified claims I flagged ("rm does not revive the daemon" and "`claude agents --json` still answers"). |
| **M5** | `stop` unclassified; spec's justification false at 2 of 5 call sites | **FIXED** | `_stop_native_session_status` added, sharing `_classify_native_cli_result`; `_stop_native_session` kept as its bool face. `_cmd_kill_native` reports `stop_outcome` verbatim, `'timeout'` is gone, and the spec now reads "…**was** left unchanged because 'callers re-check the roster'…" — the false claim is retracted, not quietly dropped. `test_kill_on_an_already_gone_sid_stamps_outcome_true` also pins the G10 tombstone on the gone path. **See ND-1.** |
| **m1** | `gone` short-circuit is the one fail-unsafe direction | **FIXED as named** (on `rm`) | Both hygiene call sites pass the roster entry's own `id`; `test_sweep_passes_the_rosters_own_id_not_a_derived_ref` pins it with an `id` deliberately unequal to the derived prefix. Injection H red. Fallback verified independently — see **Surface 2**. **Not applied to `stop` — ND-1.** |
| **m2** | pin samples the confound | **FIXED as named** | Test 5 branches on `"deferred (daemon-transient)" in a.stderr`. **See ND-2 and Surface 4.** |
| **m3** | G12 column self-contradicts | **FIXED** | Both superseded items struck through and tagged `[SUPERSEDED …]`; the still-genuinely-UNOBSERVED third (transcript clearing) correctly left alone. Verdict untouched — no self-ratification. |
| **m4** | test never asserted "still archives" | **FIXED** | `assert dest.exists() and any(dest.iterdir())`, with a journal seeded so there is something to move. |
| **m5** | docstring miscites §Q3 | **FIXED** | Split: the full-uuid half is marked a receipt, the transient short-circuit "REASONING, NOT A RECEIPT … so it is untested". |
| **N1** | spurious `rc=1`→`rc=0` | **FIXED** | |
| **N2** | hyphen vs em-dash | **FIXED** | Em-dash everywhere, with the dash explicitly labelled a transcription choice. |
| **N3** | `no-claude`/`error` glosses unpinned | **FIXED** | `TestRmOutcomeNotes` pins all four. Injection G (wave 1: **green**) now red. |

**SPURIOUS-FIX: none.** I checked each fix against its finding: nothing was
hardened on suspicion, no roster read changed, `_stop_native_session`'s bool face
was preserved for its existing callers rather than rewritten, and the deferral was
deliberately kept out of `errors` — the one place a fix could have over-reached
into cry-wolf, and it did not.

---

# New defects

## ND-1 — MAJOR: `m1`'s hardening went to both `rm` call sites and **neither `stop` call site** — in the commit that gave `stop` the inference `m1` exists to make safe.

`eda3328` did two things at once. It taught `stop` that `gone` means success (M5),
and it taught `rm` never to trust a *derived* ref for a `gone` verdict (m1). It did
not join them up.

`_rm_native_session_status` gained a `ref` parameter, and its new docstring states
the hazard exactly right:

> `ref` (m1 fix wave …) overrides the DERIVED short id with one the caller read
> from the roster entry itself (the CLI's own `id` field). **This is the one
> direction in which classifying `gone` as success could fail UNSAFE:** the `gone`
> inference ("the sid already reached the desired end state") is sound only if the
> ref was right, and `_native_job_ref` derives it by string-splitting rather than
> reading it.

`_stop_native_session_status` accepts the same `ref` parameter and points at that
docstring:

> `ref` overrides the derived short id -- see `_rm_native_session_status` for why
> a caller holding the roster entry should pass the CLI's own `id` (m1).

**Neither stop call site passes it** (`bin/fleet.py:3938-3942`, `:3955-3957`):

```python
    stop_outcome = "no-sid"
    if sid:
        stopped_ok, stop_outcome = _stop_native_session_status(sid, run=run,
                                                               which=which)
```

So `fleet kill` derives `sid.split("-", 1)[0]`, and a ref the CLI rejects answers
`No job matching` → `gone` → **success**.

**The record has the CLI's own id in hand and it is never read.** `native_short_id`
is a registry field — *"short id from --bg stdout (G6 fallback)"* (`bin/fleet.py:654`)
— and `_cmd_kill_native` already holds the record it lives on.

### Repro (run this session, `bin/fleet.py` @ `e2ee7c5`)

A stubbed CLI that answers only to its own short id — exactly the drift `m1`'s fix
exists to survive:

```
registry native_short_id (the CLI's own id) : 'zz9qk7xd'
ref fleet actually used                     : ['aaaabbbb']
fleet kill exit code                        : 0
event interrupt_outcome                     : True
registry status                             : dead
stdout                                      : w1: killed

THE SESSION WAS NEVER STOPPED -- the CLI only ever saw a ref it rejects.

Contrast, same commit, the SWEEP path (m1 fix applied):
  sweep rm ref used: ['zz9qk7xd']  <- the roster's own id. Correct.
```

Note the ref list has **one** entry: `gone` short-circuits before the full-sid
retry, so the ref the CLI *would* have accepted is never tried. The two halves of
one commit, on one machine, on one sid, disagree about which identifier to trust.

**Failure scenario.** A future CLI changes the short-id format (lengthens it,
disambiguates a collision, stops accepting the bare 8-char prefix — the same drift
class `m1` is written against). `fleet kill w1` derives a ref the daemon rejects,
reads `No job matching` as "already gone", prints `w1: killed`, exits **0**, stamps
`interrupt_outcome=True`, and marks the worker dead. **The bg session keeps
running, and fleet has just forgotten it exists** — untracked, unattributed, and
skipped by every husk sweep forever because it is `status`/`pid`-live. That is the
rogue-session class `_cleanup_wedged`'s own docstring calls a C1 CRITICAL, reached
here through the front door.

**Severity, argued honestly.** This is drift-conditional exactly like `m1` — at
2.1.212 the derived ref is correct, so nothing is broken today, and I rated `m1`
MINOR on that basis. ND-1 is MAJOR rather than MINOR for three reasons: the
consequence is a live untracked session rather than a husk leak plus a false event;
the pre-fix code was *fail-safe* on this input (rc=1, "investigate the session
manually" — cry-wolf in the common case, but it would have caught this one), so the
wave removed the only signal without making the true case detectable; and the fix
is one line, using a mechanism that shipped in the same commit.

**Named fix.** At `_cmd_kill_native`'s primary-sid stop, pass the id fleet already
captured:

```python
        stopped_ok, stop_outcome = _stop_native_session_status(
            sid, run=run, which=which, ref=rec.get("native_short_id") or None)
```

Retired sids keep the derived fallback — they have no `native_short_id`, exactly as
`_native_job_ref`'s docstring says, and that is what the fallback is for. Pin it
with the mirror of the test that already exists for the sweep
(`test_sweep_passes_the_rosters_own_id_not_a_derived_ref` →
`test_kill_stops_by_the_captured_short_id_not_a_derived_ref`).

**One honest caveat on the fix.** `native_short_id` is not uniformly the CLI's own
id today. Four of its six writes take it from `--bg` stdout (`:2307`, `:3325`,
`:3834`, `:6123`); two derive it on a fast path (`:2235`, `:3793` —
`fast_sid.partition("-")[0] or fast_sid[:8]`). So the fix is a strict improvement
on 4 of 6 paths and a no-op on the other 2, not a cure. The residual derivation is
worth its own look — it is the same "derive rather than read" pattern `m1`
condemned, sitting one layer up.

Also worth noting: `_native_job_ref`'s docstring still argues *against* this fix —
*"derive it uniformly here rather than special-casing callers that do/don't have a
stored `native_short_id`"*. That was a sound T12-era call, but `eda3328` introduced
the special-casing anyway (the `ref` parameter) and gave the reason. The docstring
is now stale and should say so.

---

## ND-2 — MINOR: the pin's `_daemon_alive()` fallback is documented but not implemented; the skip now rests entirely on the one string nobody has ever observed.

`m2`'s fix is right in substance — branching on fleet's own in-process
classification really is race-free where a later probe is not. But the comment
promises a fallback the code does not contain
(`tests/integration/test_native_pin.py:530-536`):

> `_daemon_alive()` is retained for the diagnostic paste (what makes a RED
> self-explaining) **and as the fallback when the archive path printed no
> classification line at all.**

Every use of `alive` in the file:

```
$ grep -n "alive" tests/integration/test_native_pin.py
541:    alive, status_text = _daemon_alive()
561:        f"--- claude daemon status (sampled after the fact; alive={alive!r}) "
```

Assigned once, interpolated into an assert message once. **It appears in no branch
condition.** The skip is `if leftover and rm_deferred:` and nothing else. This is
precisely the M1 defect in miniature: a comment asserting what the code does not do.

**Why it bites.** `rm_deferred` matches the literal `"deferred (daemon-transient)"`,
which fleet prints only when `_NATIVE_CLI_TRANSIENT_RE` matched — and that regex is
built on a message **two waves have now failed to observe** (M4). If the real
dead-daemon message does not contain `background service may be restarting`, the
classifier correctly falls to `failed`, fleet correctly prints `deferred (failed)`,
`rm_deferred` is `False`, and test 5 hard-asserts:

> …still present in `claude agents --json --all` after archive, and fleet did NOT
> report a daemon-transient deferral for the rm … **this is a genuine contract
> regression, not the daemon-lifecycle confound**

— on a machine whose daemon is simply down. That is the exact false-RED confound
`m2` was written to kill, reintroduced and now conditional on an unverified string.
The old `alive is False` check would have caught it. Fail-loud and test-only, so
MINOR — but it is a live-tier RED that costs a wave to diagnose.

**Named fix.** Implement the documented fallback:

```python
    rm_deferred = "deferred (daemon-transient)" in archive_err
    rm_unclassified = "deferred (" in archive_err and not rm_deferred
    alive, status_text = _daemon_alive()
    if leftover and (rm_deferred or (rm_unclassified and alive is False)):
        pytest.skip(...)
```

Fleet's classification stays primary; `_daemon_alive()` becomes the corroborating
fallback for the shape nobody has seen. Also worth pinning the coupling: test 5
matches an internal print format with nothing binding the two — rename
`_rm_outcome_note`'s output and the pin breaks silently until the next live run.
Export the literal as a constant both sides import, or assert the format in a unit
test.

---

## ND-3 — MINOR: the doctor note fires on the **first** deferral, so it fires on the normal case — which is the cry-wolf pattern this whole branch exists to kill.

`bin/fleet.py:5685-5692`:

```python
    if husks_deferred > 0:
        extras.append(
            f"last run DEFERRED {husks_deferred} husk(s) -- ...
            f"roster and every pass retries them, but a permanently "
            f"unreachable daemon starves this tier silently -- if this count "
            f"persists across runs, check `claude daemon status`")
```

The branch's own evidence says a deferral is the **routine** state for this tier.
§Q2, quoted into the spec as a hazard:

> `fleet archive` and the `fleet autoclean` scheduled task only ever run against
> workers that are *not* live, which is exactly the zero-live-worker state in which
> the daemon has idle-exited. **Fleet's hygiene tier is the one code path most
> likely to meet a dead daemon**

So on a quiet machine with hourly autoclean, the daemon is idle-exited for most
runs, every husk defers, and doctor carries this note on nearly every invocation.
An operator habituates to it in a week — and then the permanently-starved case, the
one M1 exists to surface, renders **identically**. M1's actual point was
distinguishing routine deferral from starvation, and the fix surfaces the state
without distinguishing the two.

The note text concedes the gap itself: *"if this count persists across runs"*. The
stamp holds **one** run (`bin/fleet.py:5050-5053` — a flat dict, overwritten each
pass, no history), so doctor cannot see persistence, and neither can an operator
reading doctor's output. The note asks the reader to perform a correlation the data
it is printed from cannot support.

**The data now exists.** `eda3328` added `husks_deferred` to the `autoclean_run`
event (`:5063`), and `events.jsonl` is append-only history.

**Failure scenario.** Operator runs `fleet doctor` weekly. It has said "last run
DEFERRED 2 husk(s)" every week for a month — normal, the machine is quiet. In week
five the daemon breaks permanently. Doctor says "last run DEFERRED 47 husk(s)". The
only difference is a number nobody was reading, in a note that has cried wolf 30
times.

**Named fix.** Make the note streak-aware. Either carry a counter in the stamp
(`husks_deferred_streak`: increment when `husks_deferred > 0`, reset to 0 whenever
a pass removes a husk or defers none), or have `_doctor_check_autoclean` read the
last N `autoclean_run` events and count consecutive non-zero `husks_deferred`. Note
only past a threshold (3 consecutive is a sane default — an hourly task, so ~3h of
uninterrupted starvation), and put the streak in the text: *"deferred on the last 7
consecutive runs (47 husks) — the daemon has not been reachable since <ts>"*. That
is the sentence that distinguishes starvation from Tuesday. Keep it note-only:
`ok=True` remains correct, per D4 and per `test_doctor_surfaces_a_starved_sweep`.

---

# nit

- **n1** — the corrected §Q4 receipt (M2) is *still* not a paste. Line 6858 is
  printed with 8 leading spaces; the file has 4 (line 6182, its twin, genuinely has
  8 — the indentation was copied across). 15 of 16 lines are byte-identical:
  ```
  $ git show c1277bd:bin/fleet.py > /tmp/fleet_base.py
  $ diff <(grep -n '_fetch_agents_roster(|"agents", "--json"' /tmp/fleet_base.py) <doc block>
  16c16
  < 6858:    roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731
  ---
  > 6858:        roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731
  ```
  M2's substance is fixed — the omitted `4709` row is there, bolded, with the right
  verdict — so this does not re-open it. But the fix for "hand-edited, not pasted"
  is hand-edited, on the same line pair whose `# noqa` suffix was mangled the first
  time. Re-paste the block from a real terminal.

---

# The brief's four attack surfaces

## Surface 1 — M5 stop classification: does already-gone mask a NOT-gone? Does the tombstone still get written?

**Masking: YES — see ND-1** (MAJOR, repro'd). The mechanism is a ref the CLI
rejects, not sid reuse or a stale roster id:

- **Stale roster id — not reachable.** `_cmd_kill_native` never reads the roster; it
  works from the registry record. There is no roster id to go stale.
- **Name collision — already guarded.** The `other_current_sids` check
  (`:3930-3934`) skips any retired sid matching another worker's live `session_id`
  and says so, explicitly for the corrupted-registry case.
- **Sid reuse — not applicable.** G10's respawn reuses a `sessionId` under a *new
  pid*; the ref stays valid, so `stop` still targets the right job.
- **Ref mismatch — the live one.** Prefix-derivation cannot model any short-id
  scheme that is not "first hyphen segment". This is ND-1.

**Tombstone: intact on every path. Verified, not assumed.**
`write_tombstone_outcome(name, sid, "killed")` (`:3971`) sits *before* the registry
commit and is unconditional on `stopped_ok` — the classification change cannot
reach it. `_archive_move_and_rm` is likewise still called *after* `archived_at` +
`append_event("archived")` are committed. Both are now pinned rather than
incidental: `test_kill_on_an_already_gone_sid_stamps_outcome_true` asserts the
`killed` outcome record on the gone path, and
`test_transient_rm_reports_retryable_and_still_archives` finally asserts `dest` has
content (m4). The one hole is pre-existing and unchanged: `sid is None` → no
tombstone, `stopped_ok=True`, `stop_outcome="no-sid"`.

## Surface 2 — m1 rm-by-roster-id: does the target fall back sanely when the roster entry is absent?

**YES. Verified across every malformed shape, this session:**

```
entry ABSENT (dead daemon / stale snapshot)  -> rm ref ['aaaabbbb']   # derived fallback
entry present, NO `id` key                   -> rm ref ['aaaabbbb']
entry present, id=None                       -> rm ref ['aaaabbbb']
entry present, id='' (empty)                 -> rm ref ['aaaabbbb']
entry present, id=12345 (non-str)            -> rm ref ['aaaabbbb']
entry present, id='realid8'                  -> rm ref ['realid8']    # the CLI's own id
```

The `isinstance(entry_ref, str) and entry_ref` guard covers absent / missing-key /
None / empty / non-str, and `_archive_move_and_rm` additionally guards
`isinstance(entry, dict)` for the entry itself. Absent entry → `ref=None` → derived
ref → exactly the pre-`m1` behaviour, which is the correct floor: `m1` was never a
claim that the derived ref is *wrong* today, only that a `gone` verdict should not
*rest* on it when better is available. Where nothing better is available, the
fallback is the honest answer. No new defect. `_sweep_husks` cannot hit the absent
case at all — it iterates the roster payload, so an entry always exists.

## Surface 3 — the new deferral surfaces: does doctor actually go non-green? Is the threshold sane?

**Non-green: NO — and that is correct, by design, and is what I named.** Every
return in `_doctor_check_autoclean` is `("autoclean", True, …)`; the check is
note-only per `docs/specs/autoclean.md` D4 (*"Never turns doctor red — a missing
task is a choice, not broken plumbing"*), and turning it red would contradict the
branch's own finding that a transient daemon is normal. My wave-1 named fix asked
for `extras`, which is what shipped, and `test_doctor_surfaces_a_starved_sweep`
pins `ok is True` with the comment "still note-only, never red". The note **is**
visible by default — `cmd_doctor` prints one `[PASS]`/`[FAIL]` line per check with
its message, so there is no `-v` to forget.

**Starved sweep, injected — the surface works end to end:**

| surface | before the wave | at `e2ee7c5` |
|---|---|---|
| run stamp | `husks_removed=0`, no deferral field | `"husks_deferred": 1` |
| `autoclean_run` event | `husks_removed=0` | `husks_deferred=1` |
| summary line | `husks_removed=0 … errors=0` | `husks_removed=0 husks_deferred=1 …` |
| `fleet doctor` | `task installed; last run 0.3h ago` | `…; last run DEFERRED 1 husk(s) -- …` |
| exit code | 0 | 0 (deliberate — `test_deferral_is_not_an_error_and_does_not_flip_rc`) |

**Threshold: NOT sane — ND-3.** `> 0` fires on the normal case.

## Surface 4 — pin 1407757: does it still test the DAEMON, or only fleet's bookkeeping?

**It still tests the daemon.** Both assertions hit the vendor and both can fail
when the vendor changes:

- `assert not leftover` reads the **real** roster (`claude agents --json --all`)
  after a **real** `claude rm` and asserts the sid is gone. That is vendor
  behaviour, not fleet's.
- The rm-taxonomy probe runs a **real** `claude rm <short>` and asserts rc=1 +
  `no job matching`. It is the only thing in the tree that would catch the vendor
  reverting `gone` to rc=0 and rotting the classifier's `gone` branch — the exact
  "can it fail when the vendor changes again" test. It still hard-asserts.

Fleet's own classification gates only the **skip**, which is the right place for
it: "was the environment able to deliver this contract at all" is a different
question from "did the CLI honour it", and fleet's in-process verdict answers the
first without a race. The change also *narrows* one hole I did not flag in wave 1:
under the old `alive is True` gate, a `cause=upgrade` restart (which the findings
doc documents, 4/4 with live workers) would leave the daemon *alive* a second later
while rm had genuinely failed mid-restart → false RED. The new gate skips it
correctly.

The residue is ND-2: the skip is keyed on an unverified string with no fallback,
and on an internal print format with nothing binding the two.

---

# Injection table (wave 2)

Every injection applied to `bin/fleet.py`, reverted with `git checkout --
bin/fleet.py` immediately after; full `tests/` suite each time. **Final `git
status`: clean.** Baseline **1097 passed, 6 skipped**.

| # | path broken | result | note |
|---|---|---|---|
| A | `_NATIVE_CLI_TRANSIENT_RE` → never matches | 🔴 **9 failed** | was 6 in wave 1 |
| B | `_NATIVE_CLI_GONE_RE` → never matches | 🔴 **13 failed** | was 7 |
| C | classifier tie-break: `gone` before `daemon-transient` | 🔴 **1 failed** | |
| D | `rm`'s transient retry short-circuit deleted | 🔴 **1 failed** | |
| E | rc=0 fast path deleted | 🔴 **24 failed** | was 4 |
| **F** | **entire `if deferred:` roll-up deleted** | 🔴 **1 failed** | **wave 1: GREEN (this was M1)** |
| **F2** | **`husks_deferred` dropped from the run stamp** | 🔴 **2 failed** | new surface |
| **G** | **`_rm_outcome_note` `no-claude`/`error` → `"XXX"`** | 🔴 **2 failed** | **wave 1: GREEN (this was N3)** |
| **H** | **`_sweep_husks` reverts to the derived ref (m1 undone)** | 🔴 **1 failed** | new surface |
| **I** | **`stop`: `gone` back to failure (M5 undone)** | 🔴 **6 failed** | new surface |
| **J** | **unknown message shape → `gone` (fail-safe inverted)** | 🔴 **18 failed** | new surface |
| **K** | **doctor drops the `husks_deferred` note (M1 surface gone)** | 🔴 **1 failed** | new surface |

**12 / 12 red.** Both wave-1 green probes are now pinned. The blast radius of the
original five grew (A 6→9, B 7→13, E 4→24), which is what a real pin tier looks
like. Injection J is the one I care about most: inverting the fail-safe guarantee
kills 18 tests, so M4's "diagnosis degrades, correctness does not" is now contract.

**No injection stayed green.** I could not construct one against the new code that
did — including against the ND-1 path, because ND-1 is not a broken line to revert:
it is a call that was never made. That is precisely why it needed a repro instead.

---

# Receipts re-run (wave 2)

| # | receipt | result |
|---|---|---|
| M3 counts | `grep -c` idle_exit / live_workers=0 / upgrade / live_workers values / shutting down / daemon start | ✅ **15 / 15 / 4 / `1 1 4 1` / 19 / 25** — all six match the corrected doc |
| M2 grep | `grep -n '_fetch_agents_roster(...)'` @ `c1277bd` | ✅ **16 hits**, `4709` and `6591` both present in the doc's block and the table; ⚠️ 1 line's indentation still fabricated (**n1**) |
| Suite | `py -3.13 -m pytest tests/ -q` | ✅ **1097 passed, 6 skipped** before and after all 12 injections |
| Pin | `FLEET_LIVE=1 pytest tests/integration/test_native_pin.py -q` | ✅ **6 passed in 69.04s** on the rewritten test 5 |
| ND-1 | `fleet kill` with a CLI that rejects the derived ref | ❌ **rc=0, `w1: killed`, `interrupt_outcome=True`, status=dead** — session never stopped |
| Surface 2 | `_archive_move_and_rm` ref selection across 6 entry shapes | ✅ derived fallback in all 5 malformed/absent shapes |

## Still unreachable — unchanged from wave 1

Every dead-daemon receipt. I remain a `--bg` session, so the daemon cannot
idle-exit while I run, and the only routes are banned (`claude daemon stop`) or not
mine to take. The transient message's exact bytes, "rm does not revive the daemon",
and "`claude agents --json` still answers with the daemon down" are all still
manager reports. **The fix wave handled this correctly** — it did not quietly
inherit them: the stub is tagged, the regex is deliberately narrow, the fail-safe
fallback is now pinned, and spec operator item 5 asks for the capture by name. This
is the right disposition for evidence nobody in the chain can reach; it is not a
finding against the wave, and it should not block the merge. It should block
*ratification* of G12's dead-daemon bullet, which is exactly what the spec now says.

---

`RE-REVIEW VERDICT: fix-wave(ND-1, ND-2, ND-3)`

---

# RE-REVIEW 2 — 2026-07-17 (wave 3, final gate)

Scope: wave-2 commits `f2047c1` (stop by the captured short id; streak-threshold
the doctor note) and `1e88d51` (the `_daemon_alive` fallback; n1; the spec
correction) against the three defects wave 2 named. New-defect hunt scoped to the
changed lines, per the brief's three named surfaces.

## RE-REVIEW VERDICT: merge

**ND-1 FIXED. ND-2 FIXED. ND-3 FIXED. n1 FIXED.** 0 NOT-FIXED, 0 REGRESSED,
**SPURIOUS-FIX: none.** One new MINOR (**ND-4**) and three nits, none of them a
defect in shipped behavior: ND-4 is a fail-direction trade inside the *live pin's*
skip gate, and the nits are prose that overstates what the code does. All four are
follow-ups, not merge blockers — recorded below with the reasoning that got there.

**Suite 1110 passed / 6 skipped** (was 1097; +13) before and after every injection.
**Injections 15/15 red** (my 12, re-run; the builder's 3 revert-injections).
**Tree clean.**

Every claim the fix wave made about its own limits, I checked rather than took.
All of them held — including the two it would have been easiest to fudge (the
"2 of 6 derived write paths" count and the "no-op, not a cure" characterisation
of what `ref=native_short_id` buys on those paths). That is the headline: this
wave's self-reporting is accurate, and its residuals are labeled where a reader
will meet them.

## Disposition

| # | wave-2 finding | disposition |
|---|---|---|
| **ND-1** | MAJOR. `m1`'s `ref` hardening reached both `rm` sites and neither `stop` site. | **FIXED — re-repro'd independently.** See below. |
| **ND-2** | MINOR. The pin's `_daemon_alive()` fallback was documented and never implemented. | **FIXED as named** — `alive` is now in a branch condition. But the fix trades a certain false-RED for a possible false-SKIP without saying so: **ND-4**. |
| **ND-3** | MINOR. The doctor note fired on the first deferral (the routine case). | **FIXED as named.** Streak from `events.jsonl`, threshold 3, pinned on both sides of the boundary. Reset rule is sound; its *description* is not (**n3**). |
| **n1** | the §Q4 receipt was still hand-edited (6858 indented 8, file has 4). | **FIXED**, and the builder's "verified mechanically" claim is itself true — I re-diffed it (below). |

### ND-1 — FIXED, re-repro'd from scratch

I did not take the builder's repro on trust; the previous job's script died with its
job dir, so I rebuilt it. A stateful fake CLI that answers **only** to its own short
id (`zz9qk7xd`), against a record whose sid derives to something else
(`aaaabbbb-…`), driven through `_cmd_kill_native` — with the session's liveness as
**real state**, not an assertion about a ref:

```
--- before (e2ee7c5) ---
  refs tried        : ['aaaabbbb']
  fleet kill rc     : 0
  worker status     : dead
  interrupt_outcome : [True]
  SESSION RUNNING?  : True   <-- ground truth
  VERDICT           : *** LIVE UNTRACKED SESSION -- fleet reported success ***
--- after (HEAD) ---
  refs tried        : ['zz9qk7xd']
  fleet kill rc     : 0
  worker status     : dead
  interrupt_outcome : [True]
  SESSION RUNNING?  : False  <-- ground truth
  VERDICT           : session really stopped
```

Reproduces wave 2's finding exactly, and the fix closes it. `w1: killed` + rc=0 +
`interrupt_outcome=True` + `status=dead` are printed in **both** runs — which is the
point: the durable record is identical whether or not a live session was left
behind. Nothing downstream could ever have told them apart.

**The residual claims check out — both of them.** The brief asked whether the
2-of-6 derived write paths are honestly labeled or silently relied on. Enumerated:
6 writes at `:2235 :2307 :3325 :3793 :3834 :6241` (`:654` is the `None` initializer).
Derived: `:2235` and `:3793` (`fast_sid.partition("-")[0] or fast_sid[:8]`) —
**exactly the two named**, no more. And "no-op, not a cure" is precise rather than
generous: `partition("-")[0]` and `_native_job_ref`'s `split("-", 1)[0]` agree on
every realistic sid shape (the `or fast_sid[:8]` arm can only fire on a
leading-hyphen or empty sid), so on those two paths `ref=native_short_id` passes the
*same bytes* the derivation would have. Not a regression, not a fix — a no-op, as
stated. The reliance is labeled at the point of use (`_cmd_kill_native`), in
`_native_job_ref`'s now-stale-marked docstring, and escalated to spec operator item
#5. **Not silently relied on.** One gap: **n2**, below.

### ND-2 — FIXED as named, and the fix has a fail-direction the comment does not name

`alive` is now load-bearing: `if leftover and (rm_deferred or (rm_unclassified and
alive is False))`. The documented fallback exists. Fixed.

The brief asked whether it can false-positive off a stale roster: **it cannot, as
framed** — `_daemon_alive()` shells `claude daemon status`, it does not read the
roster, so there is no stale-roster vector. The real vector is the sampling race,
and it points the wrong way. See **ND-4**.

### ND-3 — FIXED as named; boundary is pinned, reset is sound

Off-by-one at the boundary: **none in the code.** `streak >= THRESHOLD` notes *at*
3, and both sides are pinned — `test_doctor_is_silent_below_the_threshold`
(`THRESHOLD - 1`) and `test_doctor_reports_at_the_threshold_with_the_streak`
(`THRESHOLD`), both written against the constant rather than a literal, so the pins
survive a threshold change. The prose is off by one, not the code (**n3**).

Does the streak reset on a successful sweep? **Yes — and on more than that**, which
I chased because the shipped description and the code disagree. Measured:

```
after 3 deferring runs      streak = 3
after a nothing-to-do pass  streak = 0     <-- removed=0, deferred=0
after 2 more deferring runs streak = 2
```

The disposition table says the streak resets "on any pass that **removed a husk**
(proof the daemon was reachable)". The code resets on any pass that **deferred
nothing** — a superset that includes the pass which did nothing at all and therefore
proved nothing about reachability. I pushed on whether that can hide a starved tier
and **it cannot**, for two reasons worth recording because they are what makes the
code right and the sentence wrong:

1. A deferred husk **stays on the roster**, so the next pass sees it and defers
   again. An empty pass between two deferrals means the husk left by some other
   route — i.e. something was reclaiming, i.e. not starving.
2. The case where a dead daemon could *itself* empty the husk list — `claude agents
   --json` failing — does not reach this path: `_sweep_husks` raises `FleetCliError`,
   `cmd_autoclean`'s tier isolation appends to `errors`, rc flips to 1, and
   `_doctor_check_autoclean` surfaces it through the *separate* `run_errors` extra.
   Loud, not silent.

So: behavior sound, description wrong (**n3**). Also checked and clean: dry-run
writes neither the stamp nor the event, so the two surfaces cannot diverge.

---

# New defects (wave 3)

## ND-4 — MINOR: the ND-2 fix puts the racy probe back in the gate that `m2` banned it from, and its comment enumerates only the harmless direction

`m2`'s comment — **still there, fifteen lines above the fix** — is an argument for
keeping `_daemon_alive()` out of the branch condition, and it names this exact
failure:

> `_daemon_alive()` SAMPLES the confound; it does not control it, and it is racy in
> BOTH directions. […] So the daemon can be ALIVE during rm (rm works, roster should
> be clean) and DEAD by the sample: **a genuine regression would then be converted
> into a skip, i.e. the suite would report success for the exact break it exists to
> catch.**

ND-2's fix then gates on `alive is False`. In the unclassified branch, `alive` is
not corroboration — it is the **only** discriminator, because `deferred (failed)` is
what fleet prints for *both* "the dead-daemon message drifted" (M4) and "`claude rm`
genuinely regressed". The concrete false-SKIP: daemon alive at rm → rm regresses →
`deferred (failed)` → `rm_unclassified` → daemon idle-exits before the sample →
`alive is False` → **skip**, green suite, regression masked.

The new comment says the pin "can still fail on vendor drift: a leftover sid with NO
deferral line at all, or with a live/unknown daemon, still hard-asserts" — all
false-**RED** residuals. The false-**SKIP** it just introduced, the one m2 wrote a
paragraph about, is not mentioned.

**Why this is MINOR and not a blocker.** The trade is defensible and probably
correct: before the fix, the unclassified shape hard-asserted *certainly*, on every
run of a machine whose message drifted — a pin that cries wolf every run is a pin
nobody reads. The false-SKIP needs a narrow window (the test archives after >5s of
zero live workers, so the daemon is most likely *already* dead at rm, in which case
the skip is correct). It is test-only; no shipped behavior is affected. And the real
cure is M4's, already tracked as operator item #6 — get the message's bytes and the
fallback retires itself.

**What I would take, in order:** (1) name the false-SKIP in the comment — the
omission is the finding, the trade is fine; (2) if cheap, sample `_daemon_alive()`
*before* the archive as well and require both samples dead, which collapses the
window to the rm itself.

---

# nits (wave 3)

**n2** — `:654` declares the field ND-1's fix now trusts as
`"native_short_id": None, # short id from --bg stdout (G6 fallback)`. That
provenance is false on 2 of its 6 write paths, and it is the *only* comment a reader
at `:2235`/`:3793` meets while populating it. The caveat is recorded everywhere a
*consumer* looks (use site, `_native_job_ref`, spec item #5) and nowhere a *producer*
does. Cheap: mark the two fast-sid writes as derived, and soften `:654` to name both
provenances.

**n3** — the reset rule is described as "resetting on any pass that removed a husk
(proof the daemon was reachable)" (disposition table, and the commit message).
Implemented rule: reset on any pass that **deferred nothing**, which also fires on a
nothing-to-do pass that proves nothing about reachability. `_autoclean_deferral_streak`'s
own docstring gets the mechanism right ("stops at the first pass that deferred
nothing") and then attaches the same wrong justification ("a single successful sweep
means the daemon was reachable"). Behavior is sound (see ND-3 above); three of the
four places that describe it are not.

**n4** — `_doctor_check_autoclean`'s docstring says "note only **past**
`AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD` consecutive starved sweeps". The code is
`streak >= THRESHOLD` — *at* 3, not past 3. The constant's own comment, the commit
message and the disposition table all say "at". One word, in the one place a reader
checks the boundary.

Also noted, not a finding: `_autoclean_deferral_streak`'s `rec.get("dry_run")` filter
can never fire — `append_event("autoclean_run", …)` writes no `dry_run` key, and
`cmd_autoclean` skips the event entirely on a dry run. The docstring's claim that
dry-run passes "are skipped entirely" is true; the filter that appears to do it is
belt-and-braces. Harmless, and I would keep it.

---

# Injection table (wave 3)

Every injection applied to `bin/fleet.py`, reverted with `git checkout --` after;
full `tests/` suite each time. Baseline **1110 passed, 6 skipped**.

| # | path broken | result | vs. wave 2 |
|---|---|---|---|
| A | `_NATIVE_CLI_TRANSIENT_RE` → never matches | 🔴 **10 failed** | 9 |
| B | `_NATIVE_CLI_GONE_RE` → never matches | 🔴 **13 failed** | 13 |
| C | classifier tie-break: `gone` before `daemon-transient` | 🔴 **1 failed** | 1 |
| D | `rm`'s transient retry short-circuit deleted | 🔴 **1 failed** | 1 |
| E | rc=0 fast path deleted | 🔴 **24 failed** | 24 |
| F | entire `if deferred:` roll-up deleted | 🔴 **1 failed** | 1 |
| F2 | `husks_deferred` dropped from the run stamp | 🔴 **2 failed** | 2 |
| G | `_rm_outcome_note`'s `no-claude` branch key broken | 🔴 **1 failed** | 2 (broke both glosses; mine breaks one) |
| H | `_sweep_husks` reverts to the derived ref (m1 undone) | 🔴 **1 failed** | 1 |
| I | `stop`: `gone` back to failure (M5 undone) | 🔴 **6 failed** | 6 |
| J | unknown message shape → `gone` (fail-safe inverted) | 🔴 **19 failed** | 18 |
| K | doctor drops the deferral note (M1 surface gone) | 🔴 **2 failed** | 1 |
| **R1** | **ND-1 undone: `_cmd_kill_native` drops `ref=`** | 🔴 **1 failed** | builder's |
| **R2** | **ND-2 undone: `NATIVE_RM_DEFERRED_PREFIX` renamed** | 🔴 **3 failed** | builder's |
| **R3** | **ND-3 undone: note fires on the first deferral** | 🔴 **2 failed** | builder's |

**15 / 15 red.** My 12 re-run against the new code, plus the builder's 3
revert-injections independently reconstructed rather than taken on trust. The three
wave-2 fixes are each pinned by a test that dies when the fix is reverted — including
**R1**, which is the interesting one: ND-1 was "a call never made" and therefore
unrevertable in wave 2, so it needed a repro. Now that the call exists, deleting it
goes red. The finding closed *and* grew a pin.

Blast radius moved where new tests landed (A 9→10, J 18→19, K 1→2). G reads 1 rather
than wave 2's 2 because my injection breaks the `no-claude` branch key alone where
wave 2's broke both glosses — a different injection, not a weakened pin.

One process note, recorded because it is the kind of thing that quietly turns a
review into theatre: my first pass at **E** reported `PATCH-MISS (count=0)` — my
needle carried a real newline where `bin/fleet.py` has a literal `\n`. The harness
distinguishes "patch did not apply" from "patch applied, suite green", so it surfaced
as a miss rather than a silent GREEN. Re-run with a corrected matcher: 24 failed, the
same number wave 2 recorded. **A harness that cannot tell a failed patch from a
passing suite reports the reviewer's bugs as the code's virtues.**

---

# Receipts re-run (wave 3)

| # | receipt | result |
|---|---|---|
| **n1 / §Q4 grep** | doc block vs. `grep -n '_fetch_agents_roster(\|"agents", "--json"' fleet_base.py` @ `c1277bd`, `diff`'d | ✅ **16/16 lines byte-identical, 0 mismatches** — the builder's "verified mechanically" claim is itself true |
| **ND-1 repro** | rebuilt from scratch, before/after, session liveness as ground truth | ✅ reproduces at `e2ee7c5`, closed at `HEAD` |
| **2-of-6 derived paths** | enumerated all 6 `native_short_id` writes | ✅ exactly `:2235` and `:3793` — count is exact |
| **"no-op, not a cure"** | `partition("-")[0]` vs `split("-",1)[0]` over 7 sid shapes | ✅ identical on every realistic shape — no-op, as stated |
| **streak reset** | 3 deferring runs → nothing-to-do pass → 2 more | ✅ resets to 0 (see n3) |
| Suite | `py -3.13 -m pytest tests/ -q` | ✅ **1110 passed, 6 skipped** before and after all 15 injections |
| Pin | `FLEET_LIVE=1 pytest tests/integration/test_native_pin.py -q` | ✅ **6 passed in 76.53s** — 0 skipped, i.e. the ND-2 skip branch did **not** fire: the daemon was alive, rm worked, roster-gone was asserted for real |
| Tree | `git status --porcelain` | ✅ clean |

## Still unreachable — unchanged from waves 1 and 2

Every dead-daemon receipt. I am still a `--bg` session; the daemon cannot idle-exit
while I run, and the only routes to it are banned (`claude daemon stop`, machine-wide
blast radius) or not mine to take. The transient message's exact bytes remain a
manager report — which is precisely what makes ND-4's fallback necessary *and* what
makes it a stopgap. Spec operator item #6 asks for the capture by name. Unchanged
disposition: this blocks **ratification** of G12's dead-daemon bullet, not the merge.

---

`RE-REVIEW VERDICT: merge`
