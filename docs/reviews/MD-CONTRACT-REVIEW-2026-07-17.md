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
