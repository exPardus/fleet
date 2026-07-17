# Three-tier command — adversarial design review (BREAK lens)

Target: `docs/specs/three-tier-command.md` (DRAFT PROPOSAL, 2026-07-16).
Reviewer: `md-review-break` (fleet worker), 2026-07-17. Lens: hostile — how does this
fail in production, lose money, violate an operator gate, or mint a second supervisor?
No build exists; this review gates whether spec work may begin.

All CODE claims below carry a grep receipt pinned `# at c1277bd` (`git rev-parse --short
HEAD` in `C:\proga\claude-fleet` at review time). All DRAFT claims quote the draft
verbatim. `bin/fleet.py` was never read end-to-end — only the greped regions.

Findings: **5 CRITICAL, 5 HIGH, 5 MED, 2 LOW**. Verdict block at the end.

The short version: the draft's two load-bearing moves — *"supervisor as a fleet worker"*
and *"a scheduled task runs `fleet send supervisor` every N hours"* — are individually
plausible and jointly self-destroying. The supervisor claim is keyed on `session_id`; the
only channel that can start a turn in an idle session is fork-steer, which **rotates the
`session_id` by design**. So the beat is the thing that breaks the claim, on the first
firing, forever. Everything in C1–C5 follows from that collision or from the scheduler
running the same hygiene that eats its own supervisor.

---

## C1 — CRITICAL: the beat destroys the claim it depends on (fork-steer rotates the sid; the claim is sid-keyed)

**Draft says:**

> - time-driven: a scheduled task (`fleet init --supervisor-beat N`) runs
>   `fleet send supervisor "beat"` every N hours — same schtasks pattern as
>   autoclean, same install guards (N1 lessons apply verbatim).

and

> 2. **Supervisor as a fleet worker** — a native `--bg` session named `supervisor`,
>    spawned by `fleet sup-spawn` (new), holding the claim via the existing sup-boot
>    ritual inside its first turn.

**The collision.** `fleet send` to an *idle* worker is a fork-steer, and a fork-steer mints
a new sid and retires the old one:

```
# grep -n "def _restamp_after_steer" -A 22 bin/fleet.py   # at c1277bd
5877:def _restamp_after_steer(record: dict, new_sid: str, short_id: str) -> None:
5878-    """Mutate `record` in place after a fork-steer (`send`'s idle path,
5879-    `resume-limited`'s native branch): retire the OLD sid into
5880-    retired_sids, restamp session_id/native_short_id to the new fork,
...
5896-    old_sid = record["session_id"]
5897-    if old_sid is not None:
5898-        record["retired_sids"] = list(record.get("retired_sids", [])) + [old_sid]
5899-    record["session_id"] = new_sid
```

Nothing on that path touches `supervisor/INCARNATION` — the claim keeps naming the sid that
was just retired:

```
# grep -n "INCARNATION\|incarnation_path\|write_incarnation" bin/fleet.py   # at c1277bd
6360:# supervisor/JOURNAL.md append-only). Body claim = supervisor/INCARNATION
6395:def incarnation_path() -> Path:
6446:    _write_json_atomic(incarnation_path(), claim)
6717:        lines.append(f"INCARNATION: {inc_line}")
7070:            return f"SUPERVISOR: claim {inc} heartbeat unreadable -- inspect supervisor/INCARNATION."
```

(`write_incarnation` is defined @6444 — the `_write_json_atomic` line 6446 above is its body.
Its callers, `grep -n "write_incarnation(" bin/fleet.py` at c1277bd: @6691 and @6705 —
`cmd_sup_boot`'s claim and seize branches — plus @6750/@6761 (checkpoint/heartbeat refresh),
@6950 (handoff-complete's transfer) and @7019 (handoff-abort). Seven call sites, every one a
`sup-*` verb. None of them is `send`.)

And the claim is enforced by exact sid equality:

```
# grep -n "def _require_claim_holder" -A 14 bin/fleet.py   # at c1277bd
6723:def _require_claim_holder(sid_override=None):
...
6733:    if caller != claim.get("session_id"):
6734-        raise FleetCliError(
6735-            f"caller sid {caller} does not hold the claim (holder: "
6736-            f"{claim.get('incarnation_id', '?')} sid {claim.get('session_id')}) -- "
6737-            f"the journal is single-writer, claim-holder-only (spec §4)")
```

**Failure scenario (concrete).** `fleet sup-spawn` mints the supervisor body S1; its first
turn runs `sup-boot` → claim `{inc-A, session_id: S1}`. N hours later the scheduled task
runs `fleet send supervisor "beat"`. The worker is idle → fork-steer → the beat turn runs in
body **S2**, registry restamped, S1 in `retired_sids`, INCARNATION still says S1. The beat
body now:

- runs `fleet sup-heartbeat` → **FleetCliError** ("caller sid S2 does not hold the claim") —
  the heartbeat can never be refreshed again;
- runs `fleet sup-checkpoint` → same error — the supervisor can never journal again, so the
  soul-file continuity the whole design rests on stops at beat #1;
- runs `fleet sup-boot` to recover → `supervisor_claim_decision` is handed `live_sids` from
  the roster. S1 is a forked-from predecessor, not a live process, so it is not in
  `live_sids` (`_roster_live_sids` @6532 requires a `status`/`pid` key). Verdict is then
  decided purely by heartbeat age: `age > 3600s` ⇒ **seize**, else ⇒ **freeze**.

```
# sed -n '6560,6598p' bin/fleet.py   # at c1277bd
6560:def supervisor_claim_decision(claim, live_sids: set, latest_entry, now=None,
6561-                              stale_seconds: float = SUPERVISOR_CLAIM_STALE_SECONDS):
...
6573:    if holder_sid in live_sids:
6574-        return ("refuse", ...)
...
6594:    if age > stale_seconds:
6595-        return ("seize", f"holder roster-gone, heartbeat stale ...")
6596-    return ("freeze", f"holder roster-gone but heartbeat fresh ({age:.0f}s <= "
6597-                      f"{stale_seconds:.0f}s) -- daemon restart? (G9). Never seize on ambiguity.")
```

So there are exactly two steady states, both broken:

- **N < 1h** → every beat lands on `freeze` (rc 3). The skill's boot ritual says freeze means
  "PAGE THE OPERATOR. Never seize" — the unattended supervisor's entire job becomes paging a
  human every N hours. This is *precisely* this morning's incident ("roster-gone but
  heartbeat fresh — daemon restart? (G9)"), except the draft schedules it.
- **N > 1h** → the heartbeat is always stale by beat time (it can't be refreshed, per above),
  so every beat **seizes from its own predecessor body**: a new `inc-*` id, a `SEIZED`
  journal entry, every N hours, forever. The incarnation id — the durable identity the whole
  §12 protocol keys on — churns once per beat, and `SEIZED` (a *recovery* signal an operator
  is supposed to be able to trust) becomes routine noise.

**Named fix.** The claim must not be keyed on a value that fleet itself rotates. Options,
in my order of preference:

1. **Key the claim on the worker name + a per-body nonce, not the sid.** `INCARNATION` grows
   `worker_name` and `body_nonce`; `_require_claim_holder` accepts a caller whose *current
   registry sid* for that name equals the caller's sid (one registry read), and the nonce
   discriminates two bodies sharing a sid (the C2/fork-session class). The registry is
   already the single source of "which sid is this name right now" and is already restamped
   by `_restamp_after_steer`.
2. **Make `send`'s fork-steer restamp the claim** when the target name is the claim holder's
   worker. Cheap, but puts a supervisor-protocol write inside the generic steer path and
   still leaves the "two bodies, one sid" hole open.

**Design question the spec must answer before build:** what *is* a supervisor body's
identity, given that fleet mints a new sid on every steer, every resume, and every respawn?
Until that has an answer, `sup-spawn` should not be written.

---

## C2 — CRITICAL: the claim gates only the journal — a beat can resurrect a superseded body, and nothing stops it acting

**Draft says:**

> Supervisor **identity** already survives bodies (GOALS.md + JOURNAL.md +
> INCARNATION claim + seize/handoff rituals, spec §4). What does NOT exist: a body
> that acts without a human-attached session driving it.

The draft reads the claim as if holding it conferred the right to act, and lacking it
conferred restraint. It does not. Every caller of the claim guard:

```
# grep -n "_require_claim_holder(" bin/fleet.py   # at c1277bd
6723:def _require_claim_holder(sid_override=None):
6747:        claim, caller = _require_claim_holder(getattr(args, "sid", None))   # cmd_sup_checkpoint
6759:        claim, _ = _require_claim_holder(getattr(args, "sid", None))        # cmd_sup_heartbeat
6833:        claim, caller = _require_claim_holder(getattr(args, "sid", None))   # sup-handoff-begin
6937:        claim, caller = _require_claim_holder(getattr(args, "sid", None))   # sup-handoff-complete
6985:        claim, caller = _require_claim_holder(getattr(args, "sid", None))   # sup-handoff-abort
```

Five callers, all `sup-*`. **`spawn`, `send`, `kill`, `clean`, `respawn`, `archive`,
`autoclean`, and every git operation are unguarded by the claim.** The claim is an advisory
lock over `supervisor/JOURNAL.md` and nothing else. That was survivable when the body was a
human-attached session (a human is the mutex). The draft removes the human and keeps the
advisory lock.

**Failure scenario (concrete), answering the brief's question "Can a beat resurrect a
superseded body?" — yes, mechanically:**

Old body S1 completes a handoff (`sup-handoff-complete` transfers the claim to successor
S9) and, per the skill, "EXIT the session. No further fleet actions." The session is now
idle-with-transcript, still registered under name `supervisor`, still in the roster. The
scheduled task fires `fleet send supervisor "beat"`. `send` resolves the name from the
registry — which, if handoff dispatched the successor under a *different* name, still points
at S1 → fork-steer → **S1 wakes up with its full pre-handoff context, believing it is the
supervisor**, and starts dispatching. Its `sup-checkpoint` calls fail (C1's error), which it
will read as a claim problem, not a "you are dead" signal — and every non-`sup-*` verb works
fine. Two supervisors, one of them acting on a stale world model. This is the 2026-07-16
two-manager incident with the human replaced by cron.

The `--fork-session` zombie of `2026-07-17-mc` is the same class and the draft's own proposed
mitigation is insufficient for it:

> The sup-claim CANNOT see this — both bodies share incarnation id + sid; a per-body nonce is
> the fix candidate (logged in three-tier-command.md).

A nonce that only the *journal* checks stops a zombie from journaling. It does not stop a
zombie from spawning workers, sending phantom steers (7 observed), merging, or pushing —
which is exactly what the observed zombie did.

**Named fix.** Pick one and spec it:

1. **Make the claim load-bearing for mutations, not just the journal.** A `supervisor_mode`
   marker (env or registry flag) makes fleet require a valid claim+nonce for the mutating
   verbs *when the caller is a fleet-managed session*, refusing loudly otherwise. Cost: a
   claim read on every mutating verb; a human at a shell stays unguarded (same carve-out as
   `_confirm_destructive`'s `caller is None` branch).
2. **Or: fence the body, not the verb.** On handoff-complete / seize, the *winning* side
   `claude stop`s the superseded sid (fleet already owns "stop then verify via roster" —
   `respawn --force`'s shape, SPEC §7) and writes its tombstone. A stopped body cannot be
   fork-steered by a beat and its ScheduleWakeup dies with it (G7).

Option 2 is smaller and closes the beat-resurrection path; option 1 is what actually closes
the zombie class. My recommendation: **both**, and until at least one exists, "the supervisor
runs unattended" is not a safe claim to make.

---

## C3 — CRITICAL: the beat period and `SUPERVISOR_CLAIM_STALE_SECONDS` are structurally incompatible — the claim is seizable for N−1 hours of every N

**Draft says:** "a scheduled task ... runs `fleet send supervisor "beat"` **every N hours**".

```
# grep -n "SUPERVISOR_CLAIM_STALE_SECONDS = " bin/fleet.py   # at c1277bd
6367:SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0   # S: seizure/nag threshold, > beat period + margin (spec §4)
```

The constant's own comment states its sizing assumption: **`S > beat period + margin`**. It
was chosen for an attended session heartbeating every few minutes (spec §12: "keep the
heartbeat younger than 60 min"). The draft inverts the relation — beat period *hours*, S
*one hour* — without noting it.

**Failure scenario.** Even after C1 is fixed (say the beat body can heartbeat again), a
supervisor beating every 6h has a fresh heartbeat for 60 minutes and a **stale one for the
other 5 hours**. During those 5 hours:

- `fleet doctor` NOTEs a stale claim continuously (`_doctor_check_supervisor_claim` @7079)
  and the statusline nag (`supervisor_status_line` @7049) is permanently lit — the nag that
  is supposed to mean "the supervisor is gone" now means nothing, and an operator learns to
  ignore it. That is the alarm-fatigue failure, and it disarms the *real* signal.
- The operator's own morning session runs `sup-boot` and gets **`seize`** — correctly, per
  the rules, against a perfectly healthy scheduled supervisor. Now there are two claim-
  holding bodies and the scheduled one will discover it only at its next beat (and per C2
  will keep acting regardless).

**Named fix.** The heartbeat must be decoupled from the beat: either (a) the scheduled task
runs `fleet sup-heartbeat` on a *short* independent schedule (but see M2 — schtasks `/MO`
minimum granularity and the 1..23 hour clamp) — this is a lock-refresh, not a model turn, so
it costs $0; or (b) `S` becomes a function of the configured beat period (`S = 2N + margin`,
written into `INCARNATION` at claim time so every reader agrees), not a constant. **Design
question:** a supervisor that is *deliberately* silent for 6h and a supervisor that *died*
are indistinguishable by heartbeat age alone. What distinguishes them? (Suggestion: the
claim records `next_beat_expected_at`; stale = "missed its own scheduled beat", not
"heartbeat older than one hour".)

---

## C4 — CRITICAL: the fleet's own scheduled hygiene archives the supervisor, and archive is a one-way door

**Draft says:** "No new substrate: ... The delta is one spawn verb, one scheduled-task
variant, and doctrine." — and treats the supervisor as "a native `--bg` session named
`supervisor`", i.e. **an ordinary registry worker**. Ordinary workers get archived.

```
# grep -n "ARCHIVE_TTL_HOURS_DEFAULT" bin/fleet.py   # at c1277bd
4247:ARCHIVE_TTL_HOURS_DEFAULT = 24.0

# sed -n '4250,4262p' bin/fleet.py   # at c1277bd
4250:def _archive_eligible(name: str, record: dict, roster_entries: list, now,
...
4256-    2. status in {"idle", "dead", "interrupted"} (the recomputed verdict ...
4258-    3. roster entry for the current sid is absent OR dead (no `status`/
4259-       `pid` keys) -- NEVER archive a live-process entry (G12 gap).
4260-    4. an outcome record exists for the current sid (ANY kind ...
```

An idle-between-beats supervisor satisfies every gate: native ✓, status `idle` ✓, roster
entry dead/absent once the daemon reaps it (or, post-2.1.212, once the daemon idle-exits —
see C5) ✓, an outcome record exists from its last beat ✓. The only thing standing between
the supervisor and the archiver is **TTL 24h vs. a beat period the scheduler clamps at 23h**:

```
# sed -n '4958,4964p' bin/fleet.py   # at c1277bd
4958:def _install_autoclean_task(interval_hours, force: bool) -> None:
...
4962-    if not 1 <= interval_hours <= 23:
4963-        raise FleetCliError("--autoclean-interval-hours must be 1..23 (schtasks /SC HOURLY /MO)")
```

A one-hour margin, and the draft never mentions it.

**Failure scenario.** Operator sets `--supervisor-beat 12`. The machine is off overnight (or
the beat fails once — see H3 — or a `limited` park swallows a beat, or the operator's laptop
sleeps through two firings). 24h of `last_activity` staleness elapses. The **autoclean
scheduled task** (default 6-hourly, already shipped in M-C) runs tier 1 and archives the
supervisor: evidence files moved to `logs/archive/supervisor/`, `claude rm` on its current
and retired sids (SPEC §11 — the session is *deleted*, not just tombstoned), `archived_at`
stamped. From that instant:

```
# grep -n "def refuse_if_archived" -A 7 bin/fleet.py   # at c1277bd
152:def refuse_if_archived(name: str, record: dict, action: str) -> None:
153-    """M-B T9 (spec §5.1.2): a tombstoned (archived_at set) worker is
154-    history-only -- every native mutating command refuses it up front
155-    rather than silently reanimating or re-touching a retired record.
```

…every subsequent `fleet send supervisor "beat"` **refuses**. The scheduled task's stderr
goes to nobody (H3). The supervisor is gone, its session `claude rm`-ed, and the only signal
is a doctor note nobody is scheduled to read. The fleet has quietly decapitated itself and
the operator finds out days later.

**Named fix.** The supervisor record must be **protected from archive and from autoclean
tier 2 by construction**, not by TTL arithmetic: a `protected: true` / `category ==
"supervisor"` gate as gate 0 of `_archive_eligible`, plus the same exclusion in the
ownership discriminator's `protected` set. And spec the inverse: **what *should* retire a
supervisor?** (Answer candidate: only `sup-handoff-complete` and an explicit operator verb —
never a TTL.) This gate must ship in the same commit as `sup-spawn`, or the first
long-weekend kills the design in production.

---

## C5 — CRITICAL: the transient daemon (2.1.212) makes the roster confidently wrong, and every claim decision reads the roster

**Draft says:**

> Workers are native `--bg` sessions: durable, survive host restarts (proven
> 2026-07-16 — two host process deaths mid-campaign, zero loss), but they only run
> when a turn is dispatched. Nothing self-continues.

The draft was written against 2.1.211, where the daemon was a persistent service. As of
2026-07-17 the daemon is **transient**: it starts on demand at dispatch and exits ~5s after
the last client disconnects; `claude agents --json` then serves a **stale `roster.json`
snapshot** (per the operator's substrate note; `md-contract` is characterizing — I reason
from the design only and duplicate none of its probing).

Fleet's entire epoch defense is built for the roster being *empty or unavailable*, never for
it being *confidently wrong*:

```
# sed -n '6548,6558p' bin/fleet.py   # at c1277bd
6548:def supervisor_epoch_check(roster_ok: bool, payload):
6549-    """Roster-epoch sanity check, run BEFORE any claim decision (spec §4).
6550-    A failed or empty roster freezes the decision -- a daemon restart (G9)
6551-    must never let a fresh boot seize a claim whose holder is alive."""
6552-    if not roster_ok:
6553-        return (False, f"roster unavailable ({payload}) -- freeze, never decide blind")
6554-    if not payload:
6555-        return (False, "roster is EMPTY -- not even this session is listed; "
6556-                       "daemon restart suspected (G9). Freeze + page operator.")
6557-    return (True, f"roster holds {len(payload)} entr{'y' if len(payload) == 1 else 'ies'}")
```

A stale-but-populated `roster.json` returns `(True, ...)` — **epoch check passes**. G9 does
not fire. Every downstream verdict is then computed against a snapshot of the past.

**Two concrete failures, both new since 2026-07-17:**

1. **Stale-live ⇒ permanent refuse.** The snapshot still carries the previous body's entry
   *with* a `status`/`pid` key (it was live when the daemon died). `_roster_live_sids`
   @6532 admits it → `supervisor_claim_decision` returns **`refuse`** ("claim holder is live
   in the roster") to a supervisor whose holder is provably a corpse. The claim can never be
   recovered — and there is **no CLI verb to release it** (M4). Note the asymmetry the draft
   must reckon with: fleet's ambiguity doctrine ("never seize on ambiguity") is safe when the
   roster errs toward *empty*; a roster that errs toward *live* converts the same doctrine
   into a permanent deadlock.
2. **Stale-idle ⇒ two live bodies.** The snapshot shows the supervisor `idle` while a beat
   turn is *actually running* (dispatch revived the daemon; the snapshot predates it).
   `_cmd_send_native` picks its branch from that roster: `working` → mailbox append;
   `idle` → **fork-steer**. A stale `idle` on a genuinely-busy supervisor ⇒ a second live
   body under one name — the exact disaster `_await_attach`'s C1 wedge-retry logic exists to
   prevent ("two live sessions on one task file is the disaster case", SPEC §6). Invariant 7
   ("one live session per name") is enforced by the pre-claim + restamp, all of which trust
   the roster.

Conversely, a stale `busy` on an idle supervisor makes the beat a **silent no-op**: mail is
appended to `mailbox/<sid>.md` and no turn is ever dispatched to drain it. The scheduled task
exits 0. The supervisor never beats again and nothing anywhere reports it.

**Named fix / design question.** The draft cannot be specced until the substrate contract is
re-pinned. Concretely: (a) `md-contract`'s findings must land in `docs/specs/native-substrate.md`
*before* three-tier gets a spec — the roster's freshness semantics are now a G-row question,
not an implementation detail; (b) the epoch check needs a **staleness** axis, not just an
empty/failed axis (candidate: the roster snapshot's own mtime/generation vs. `last_dispatch_at`
— a roster older than our own most recent dispatch is not evidence about anything); (c) the
2026-07-17-mc lesson generalizes and should be quoted in the spec: *"contract field-presence
tables need a TIME AXIS — a rule true at steady-state can be false during transitions."* The
transient daemon makes the entire roster a transition.

---

## H1 — HIGH: "cheapest-capable model for the beat" is unimplementable — `model` is spawn-immutable

**Draft says:**

> - **Beat cost.** A scheduled supervisor beat is a model turn every N hours
>   forever. GOALS frugality: long beats, event-driven silence, cheapest-capable
>   model for the beat turn (a beat that finds nothing should cost cents).

The supervisor is one worker record, and its model is fixed at spawn:

```
# SPEC §4 (docs/SPEC.md:121), descriptive of bin/fleet.py at c63d7dd:
# "**Spawn-immutable fields:** `mode`/`cwd`/`model`/`setting_sources`/`token_ceiling`/
#  `spawned_by` are recorded at spawn and re-passed by every later launch path
#  (steer, resume-limited, respawn carry-forward)."
```

**Failure scenario.** There is no dispatch path that varies the model per turn — a
fork-steer re-passes the recorded one. So the operator picks once, at `sup-spawn`, between:

- **haiku** — beats cost cents (goal met), but this same session must slice campaigns, adjudicate
  reviews, do merges, and hold the operator-gate line. GOALS' "mid-tier for judgment, top-tier
  only where design weight demands it" says this body cannot do its job.
- **opus/sonnet** — the supervisor can do its job, and *every no-op beat is a top-tier turn*,
  forever, on a machine whose stated first line of defense is spend rate ("Limits are hit by
  spend rate; frugality is the first line of defense"). A beat that finds nothing costs
  dollars, not cents — and it is scheduled to find nothing most of the time.

Worse under fork-steer: the beat body carries the **entire prior transcript** (that is what a
fork *is* — G2(b): "new sid, full transcript carried"). Beat #100 pays cache-read on beats
#1–99. The draft's "a beat that finds nothing should cost cents" is not merely unmet — the
cost of a no-op beat **grows monotonically** with the supervisor's age. The draft's own
counter-argument ("the supervisor respawns/handoffs on the existing 300–500k band") means the
supervisor reaches the handoff band *on beats alone, having done no work* — and handoff is not
free (M3).

**Named fix.** Split the beat from the supervisor: a **`beat` worker** (haiku, spawn-immutable
model = haiku, trivially cheap) whose whole job is `fleet status --json` + `fleet doctor` and
one decision — "is there anything a supervisor must look at?" — mailing the supervisor only
when the answer is yes. The supervisor stays *event-driven silent* (GOALS' own phrase) and
top-tier. Then: who enforces the contract? Make it structural — the beat worker's `--task`
forbids every mutating verb, and its `token_ceiling` is set low enough that a beat that starts
reasoning hits the ceiling and parks. **Design question the spec must answer:** if the beat is
a separate worker, what wakes the *beat* worker? (Same scheduler; but now the thing the
scheduler fork-steers is disposable and respawn-fresh, which sidesteps C1's identity problem
entirely — a beat worker holds no claim.) I consider this the single highest-value
restructuring in this review: it fixes H1, most of H2, and defuses C1.

---

## H2 — HIGH: the only fleet-side cost bound is cumulative — wrong shape for an immortal worker; GOALS asserts two bounds that do not exist

**Draft says:** "Where is the cost bound?" is listed as a hazard but never answered.
**GOALS says (binding, not aspirational):**

> - Budget discipline applies to the supervisor itself: per-incarnation cap,
>   beat-rate bound (spec §4).

Neither exists in code. The parser has seven `sup-*` verbs and no budget among them:

```
# grep -n '"sup-' bin/fleet.py   # at c1277bd
7266:    p_supboot = sub.add_parser("sup-boot", ...)
7271:    p_supckpt = sub.add_parser("sup-checkpoint", ...)
7276:    p_supbeat = sub.add_parser("sup-heartbeat", ...)
7279:    p_supstat = sub.add_parser("sup-status", ...)
7282:    p_suphb = sub.add_parser("sup-handoff-begin", ...)
7287:    p_suphc = sub.add_parser("sup-handoff-complete", ...)
7292:    p_supha = sub.add_parser("sup-handoff-abort", ...)
```

The only cap that exists is the worker `token_ceiling`, and it is **cumulative across the
worker's whole life**, summed from the outcome store (SPEC §9: "`_native_cumulative_tokens`
(@1060) sums the outcome store; at/over ceiling the steer is refused and the worker flagged
sticky `over_ceiling`"), and it is **spawn-immutable** (§4).

**Failure scenario.** Two choices, both bad:

- `--token-ceiling <X>` at sup-spawn: the sum is monotonic and the supervisor is immortal, so
  X is reached with certainty — the only question is what week. At that moment the steer is
  refused and the record goes sticky `over_ceiling`. Every subsequent beat refuses. The
  supervisor is bricked *by design*, silently (H3), and the exit is `respawn` — which is a
  fresh dispatch with a new sid and thus C1 again, plus (per §7) respawn *also* refuses
  `--max-budget-usd` and carries `token_ceiling` forward unchanged — so the successor inherits
  the same already-exceeded... no: respawn carries the ceiling forward but the *outcome store*
  is keyed by NAME, so `_native_cumulative_tokens` keeps summing the pre-respawn turns. The
  respawned supervisor is over its ceiling on turn one. The reset lever does not reset the
  thing that bricked it.
- `--token-ceiling` omitted (`None`): **there is no cost bound at all** on a process designed
  to run forever. This is what will actually happen, because the alternative is a scheduled
  brick.

**Named fix.** A cumulative cap cannot bound an immortal actor; only a **rate** can. Spec
either (a) a per-incarnation cap that the *handoff* resets (i.e. the ceiling is checked
against tokens since `claimed_at`, not since the name's first outcome — this makes GOALS'
"per-incarnation cap" true and gives the supervisor a natural, cheap reason to hand off), or
(b) `beat_tokens_max` enforced by the beat worker's own low ceiling (H1's split makes this
nearly free). And the "beat-rate bound" GOALS asserts should become a real, checkable thing:
the scheduled task's interval is inspectable via the platform adapter's
`autoclean_task_query` shape — `fleet doctor` can NOTE a beat installed faster than the
GOALS-sanctioned floor. Until one of these exists, **GOALS §Constraints is describing a
system that does not exist**, and the three-tier design would be the first thing to depend on
the fiction.

---

## H3 — HIGH: a beat that fails fails silently, and the supervisor cannot rescue itself from the one park GOALS promises to survive

**Draft says:** the beat is `fleet send supervisor "beat"` from a scheduled task. **The
skill says** the watchtower beat is what runs the recovery sweeps:

> Each beat: `fleet status` ... then `fleet resume-limited` for any worker whose reset
> horizon has passed, then a checkpoint/heartbeat (below).

**Failure scenario.** The supervisor hits the plan wall mid-beat at 02:00. Per §10 the wall is
*silent* — no Stop hook, roster unchanged — and the next `fleet status` recompute parks the
supervisor **`limited`** (sticky). Now:

- `send` refuses a `limited` worker (SPEC §7: "Refuses: dead-suspected, dead/interrupted (→
  respawn), limited (→ resume-limited)"). So every subsequent scheduled beat **refuses**,
  exit 1, into a scheduled task whose stdout/stderr nobody reads and which has no retry, no
  alerting, and no escalation path. Compare autoclean, whose failures are also silent but
  whose *absence* merely leaves stale records; a silently-dead supervisor leaves the whole
  fleet unattended while every dashboard still says a supervisor exists (the claim file is
  still there; `sup-status` still prints a claim).
- The verb that clears a `limited` park is `fleet resume-limited` — and per the skill, **the
  supervisor is the thing that runs it**. Circular: the supervisor is the only unattended
  actor, and it cannot resume itself. GOALS standing goal 2 ("no worker, **supervisor**, or
  campaign is ever silently lost to a plan/usage limit ... Proven live, pin-tested, forever")
  is *false for the supervisor* the moment the supervisor is unattended. Today a human closes
  that loop; the draft's whole point is removing the human from the loop.

**Named fix.** Two parts, both cheap:
1. **The scheduled command must not be a bare `send`.** Spec a `fleet beat` verb (or
   `sup-beat`) that: resolves the supervisor record, runs `resume-limited supervisor
   --force-now`-equivalent recovery *for the supervisor itself* when it is parked, then
   steers. A scheduled task calling one fleet verb that owns its own error semantics is the
   pattern autoclean already established (SPEC §11 D1: "an ordinary mutating CLI verb").
2. **Beat failures need a sink.** Scheduled-task exit codes are visible to the platform
   adapter's query surface; at minimum, a beat must append an `events.jsonl` record and stamp
   `state/beat-last-run.json` (autoclean's `autoclean-last-run.json` precedent), so `fleet
   doctor` can NOTE "supervisor beat has not run since <t>" — the *only* mechanism by which a
   human ever learns the unattended tier died. **Design question:** what watches the watcher?
   If the answer is "the interface tier, when a human next talks to it", say so in the spec
   and accept the bound (the fleet is unsupervised for as long as the human is away) — but do
   not let the draft imply otherwise.

---

## H4 — HIGH: the scheduler bridge runs fleet with *human* authority; sid rotation makes the supervisor's own children foreign to it

**Draft says:** "same schtasks pattern as autoclean, same install guards (N1 lessons apply
verbatim)". The install guards do transfer. The **provenance model does not**, and the draft
does not notice.

```
# sed -n '1928,1950p' bin/fleet.py   # at c1277bd
1928:def _confirm_destructive(action: str, names: list, records: dict, assume_yes: bool) -> None:
...
1946:    caller = current_caller_session()
1947:    if caller is None:
1948:        return
1949:    foreign = [n for n in names if _worker_is_foreign(records.get(n, {}), caller)]

# grep -n "def current_caller_session" -A 8 bin/fleet.py   # at c1277bd
580:def current_caller_session() -> str | None:
587:    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
588:    return sid or None
```

**Failure scenario A — the scheduler is an unauthenticated root.** A scheduled task has no
`CLAUDE_CODE_SESSION_ID`, so `caller is None`, so `_confirm_destructive` **returns
immediately**: the destructive guard is off for anything the scheduler runs. That carve-out is
correct and well-argued for its stated threat model ("a human typing `fleet kill x` meant to
type it"), but a scheduled task is not a human who meant it. Today the only scheduled command
is `autoclean`, which has its own default-deny discriminator, so the exposure is nil. The
draft opens the scheduler to a *second* command and offers no rule bounding what may ever be
scheduled. **Fix: spec the rule now** — "the scheduler may invoke only verbs whose destructive
authority is internally bounded; `fleet beat` must be one of them" — and have `fleet init
--supervisor-beat` refuse to install anything else.

**Failure scenario B — the supervisor cannot manage its own children.** `spawned_by` records
the spawner's sid (SPEC §15) and is immutable across respawn. Supervisor body S1 spawns
workers → their `spawned_by = S1`. The first beat rotates the supervisor to S2 (C1). Now
`_worker_is_foreign(record, S2)` is **True for every worker the supervisor itself spawned** →
`fleet kill`/`clean`/`respawn` refuse without `--yes`. The unattended supervisor's only
recourse is to pass `--yes` to everything, forever — which is precisely the "over-helpful
agent under `bypassPermissions`" the guard was written to stop (its docstring names that
threat model verbatim). The draft's permission-mode hazard ("A background supervisor doing
merges/pushes needs bypass in the fleet repo — acceptable (C2 earned-privilege doctrine)")
understates this: **bypass mode plus habitual `--yes` plus no human means the last remaining
brake on a confused supervisor is gone**, and the confusion mode is the one this review
documents five ways.

**Named fix.** `spawned_by` must record the supervisor's **incarnation id** (or the C1 nonce),
not the raw sid, for fleet-managed sessions — an identity that survives the rotations fleet
itself performs. That is the same fix C1 needs, which is a good sign it is the right one.
**Containment the draft is missing entirely:** the blast radius of an unattended bypass
supervisor in the fleet repo includes `git push` to `main`. Spec the fence (candidate: the
supervisor's cwd is a worktree, never the primary checkout; pushes to `main` are an operator
gate routed via `NEEDS-OPERATOR`; the beat worker of H1 has no git authority at all).

---

## H5 — HIGH: `NEEDS-OPERATOR` is named but has no mechanism — nothing guarantees a human ever reads it, and the beat re-fires the same decision

**Draft says:**

> A background supervisor MUST route those to the interface tier and park, never
> self-approve. Today that routing surface does not exist (proposal: a
> `NEEDS-OPERATOR` journal kind + interface-tier nag on read).

The draft correctly identifies that it does not exist. It then treats "a journal kind + a nag"
as sufficient. It is not, on three counts:

1. **The kind is a closed enum — a spec delta, not doctrine.**
   ```
   # sed -n '6371,6374p' bin/fleet.py   # at c1277bd
   6371:SUPERVISOR_JOURNAL_KINDS = (
   6372:    "BOOT", "CHECKPOINT", "PROPOSAL", "SEIZED",
   6373:    "HANDOFF-BEGIN", "HANDOFF-COMPLETE", "HANDOFF-ABORT",
   6374:)
   ```
   Adding `NEEDS-OPERATOR` is one line — fine. But note what a journal *kind* is: an
   append-only prose record. It has **no state**: nothing marks it answered, so nothing can
   distinguish "operator has not seen this" from "operator saw it and said no".
2. **"Park" is undefined.** There is no supervisor park state. The registry's sticky statuses
   are `dead, over_budget, over_ceiling, limited, interrupted, attached` (SPEC §5) — none
   means "waiting for a human". So a supervisor that "parks" is just... idle. And an idle
   supervisor is exactly what the next beat **fork-steers back to life** — with the same world
   state, the same pending decision, and no memory that it already asked. The beat re-fires the
   decision every N hours. Worse: an idle supervisor with a pending question is
   `_archive_eligible` (C4).
3. **The nag is file-only and passive.** SPEC §12: "Nag predicate is file-only (views never
   probe): GOALS active AND (no claim OR heartbeat older than S)". It fires on *claim
   staleness*, not on pending decisions, and it renders in a statusline/doctor — surfaces that
   only exist when a human is already at a terminal. The draft's "interface-tier nag on read"
   requires the human to open the interface tier. **Nothing guarantees the read**, and the
   draft's own framing ("before the background supervisor times out") presumes a timeout that
   does not exist either.

**Failure scenario.** The supervisor needs HALT ratification at 03:00. It journals
`NEEDS-OPERATOR` and goes idle. Beat at 09:00: fork-steer, re-derives the same need, journals
it again. Beats at 15:00, 21:00: same. The operator opens the interface session on Monday to
four identical pages, ~$X of top-tier no-op beats (H1), and a campaign that made zero progress
over a weekend — while `sup-status` reported a healthy claim the entire time.

**Named fix.** A pending decision is **state**, not prose: `supervisor/PENDING-DECISION` (one
gitignored file, atomic-write, same shape as HANDSHAKE — a precedent that already exists for
exactly this "one party waits for another" problem), carrying `{id, question, asked_at,
asked_by_inc}`. Then: (a) the beat's first act is to read it and **exit without a model turn**
if it is unanswered (a parked beat costs ~nothing — this is the "beat that finds nothing costs
cents" the draft wants, and it's free); (b) `fleet doctor` + the statusline nag on its
presence — reusing the file-only nag predicate the terminal-surface doctrine already
sanctions; (c) the interface tier answers by writing an answer file / running a verb, which is
the *only* thing that clears it. **Design question:** is "the human is away for a week" a
supported state? If yes, the supervisor must be able to *stop beating* on an unanswered
question (b, above) rather than burning turns; if no, say so in GOALS and bound it.

---

## M1 — MED: the draft's hook-boundary claim is factually wrong, and event-driven beats are illusory regardless

**Draft says:**

> - event-driven: interface sends briefs; worker Stop-hook outcomes could enqueue
>   a "reconcile" mail (design question: hook write boundary allows outcome
>   records today, not mailbox writes — needs a sanctioned-list amendment or a
>   poll-on-beat instead);

The parenthetical is **false**. SPEC §8's sanctioned list, item (a), is *exactly* mailbox
writes:

> Hooks MAY write, and only: (a) `mailbox\<sid>.md` + its `.claimed.<pid>` rename; (b)
> `state\hook-errors.log` ...; (c) their own worker's journal, via PostCompact only; (d)
> their own worker's terminal-outcome record, via the Stop hook only.

No amendment is needed for a hook to write *a* mailbox. A design that reasons from a
misread of its own binding constraint has not been checked against the spec, and the fix wave
it implies ("amend the sanctioned list") would have been pure waste. **But the correct read
does not rescue the idea** — three deeper problems:

1. **The boundary is per-worker in spirit.** Items (c) and (d) are explicitly scoped to
   "*their own* worker"; (a) is unqualified only because a worker's mailbox writes are its own
   sid's claim-rename. A worker's Stop hook writing the **supervisor's** mailbox is a
   cross-worker write — new surface, and the spec's own phrasing suggests the authors did not
   intend (a) to license it. This needs a decision, not an assumption.
2. **A mailbox write cannot wake anything.** Mail only reaches a session when a turn is
   dispatched (mid-turn PostToolUse injection) or drained into a launch prompt. Hooks cannot
   dispatch: they never write the registry, never take `fleet.lock`, and must exit 0 on every
   path. So a Stop-hook "reconcile" mail to an **idle** supervisor sits in
   `mailbox/<sid>.md` until — a beat arrives. **The event-driven path requires the polling
   path to function.** It is not an alternative to poll-on-beat; it is a rider on it.
3. **The target sid is the thing that rotates.** The hook must address `mailbox/<supervisor
   sid>.md`, read from the registry — but C1's rotation means a hook that reads the sid
   moments before a fork-steer writes to a retired sid. `_migrate_residual_mailbox` (@5901)
   re-points late mail, but only at steer time; mail arriving after that migration, addressed
   to the retired sid, is orphaned (doctor's `mailboxes` check will NOTE it; nothing will
   deliver it). A reconcile signal that silently vanishes is worse than no signal.

**Verdict on the draft's own question — poll-on-beat vs. event-driven:** **poll-on-beat is
safer, and it is the only one that works today.** Reasons, in order: (1) it needs no new write
surface — the beat is an ordinary CLI dispatch, the most-tested path in the codebase; (2) it
is self-healing — a poll re-derives world state from the registry + outcome store, whereas an
event is a one-shot that is simply lost if the recipient's sid rotated, if the mailbox was
mid-claim, or if the hook's exception-swallow ate it (§8: hooks "never block, exit 0 on every
path" — i.e. a hook that fails to enqueue reports nothing); (3) events multiply the write
paths into the fleet's most delicate file class in exchange for latency the draft has no
requirement for — GOALS explicitly *wants* long beats, so what is the event buying? The
honest answer is: nothing the beat doesn't already give. **Recommendation: drop event-driven
from the design entirely**, and if latency ever becomes a real requirement, revisit it as its
own spec with a real mechanism (a hook cannot be the enqueuer; a `fleet` verb the hook is
allowed to *shell out to* is a different, more defensible design).

---

## M2 — MED: the beat is Windows-only and the schtasks clamp forbids the beat GOALS actually asks for

**Draft says:** "a scheduled task (`fleet init --supervisor-beat N`) ... same schtasks pattern
as autoclean". **The 2026-07-17 operator directive says** (SPEC header, PRESCRIPTIVE):

> everything must be multi-platform — Windows, macOS, and Linux. ... New features ship with
> all-OS support through the platform adapter (invariant 8, §16), or with an explicit
> `UnsupportedPlatformError` seam plus a tracked gap — never with silent Windows-only
> assumptions.

The plumbing the draft reuses raises on POSIX:

```
# grep -n "class _PosixPlatform" -A 20 bin/fleet.py   # at c1277bd
357:class _PosixPlatform:
358-    """Stub POSIX backend: every method raises UnsupportedPlatformError.
...
368-    def autoclean_task_query(self, task_name: str, run=None):
369-        self._unsupported("autoclean_task_query")
371-    def autoclean_task_install(self, task_name: str, command: str,
372-                               interval_hours: int, run=None):
373-        self._unsupported("autoclean_task_install")
```

Reusing it means the **supervisor tier does not exist on macOS or Linux** — not degraded:
absent. Autoclean's gap is survivable (a Linux operator loses hygiene, keeps the fleet); the
beat gap is not (a Linux operator loses the *supervisor*, i.e. the entire feature).
Autoclean's schtasks-only status was accepted as a *tracked gap on a shipped Windows feature*.
The draft would be shipping a **new** feature into that gap, which the directive's "never with
silent Windows-only assumptions" forbids.

**Second problem, independent of platform:** the clamp.

```
# sed -n '4962,4963p' bin/fleet.py   # at c1277bd
4962:    if not 1 <= interval_hours <= 23:
4963:        raise FleetCliError("--autoclean-interval-hours must be 1..23 (schtasks /SC HOURLY /MO)")
```

`/SC HOURLY /MO N` cannot express a daily or weekly beat. GOALS: "Idle fleet ⇒ long beats or
event-driven silence; beat rate scales with how fast the watched state actually changes, never
faster." An idle fleet's state changes on the timescale of *days*. The draft's plumbing choice
silently caps the beat at 23h and — per C4 — 23h is already inside the archiver's 24h TTL. The
cost model (H1) and the frugality goal both want the beat *longer* than the mechanism allows.

**Named fix.** Either (a) spec the cron/launchd seam **now**, as part of this design — the
adapter surface already exists and `beat_task_install/query/remove` is three methods × three
OSes (`schtasks /SC DAILY|WEEKLY` or `/SC ONCE` + re-arm for >23h; `crontab` on Linux;
`launchd` plist on macOS) — or (b) build the beat on a **portable substrate instead of the
OS scheduler**: SPEC §12 already records `ScheduleWakeup` self-rearm as the supervisor's
heartbeat primitive, "confirmed real (G7)", proven at ~3min cadence in bg sessions
(lessons, M-0). It is portable for free, needs no adapter, and has one documented failure
mode ("`claude stop` permanently kills a scheduled wake — a stopped supervisor never
self-resumes") plus one undocumented one (it dies with the host, so it cannot survive a
reboot — which is the case the OS scheduler exists for).

**The draft never mentions ScheduleWakeup at all**, though §12 names it as *the* heartbeat
primitive. That is a real gap: the design has two competing beat mechanisms in the same
system and reconciles neither. **Design question the spec must answer:** ScheduleWakeup
(portable, free, dies at stop/reboot) vs. OS scheduler (survives reboot, Windows-only today,
≤23h, unauthenticated per H4) — or both, with the OS scheduler as the *recovery* path that
restarts a supervisor whose in-session wake died, and ScheduleWakeup as the beat? That last
shape is probably right, and it is not in the draft.

---

## M3 — MED: unattended handoff has a 300s window and a human-cleared abort flag

**Draft says:** "the supervisor respawns/handoffs on the existing 300–500k band without losing
the human thread (it never had it)".

The handoff protocol is a two-party sync with a hard timeout, and (per H1) a beat-driven
supervisor will reach the band *from beats alone*:

```
# grep -n "SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS" bin/fleet.py   # at c1277bd
6368:SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0   # T: handoff wait before abort (spec §4)
```

**Failure scenario.** The unattended supervisor decides to hand off. `sup-handoff-begin`
dispatches the successor; the old body must wait for `supervisor/HANDSHAKE` within T=300s.
Post-2.1.212 the daemon is *transient*, so the successor's dispatch now includes a daemon cold
start, plus the 60s roster-join window (`SUPERVISOR_ROSTER_VERIFY_SECONDS = 60.0` @6369), plus
the successor's own first-turn model latency before it even runs `sup-boot --handoff-inc`. 300s
is not obviously enough any more, and it was calibrated on the persistent-daemon substrate. On
timeout: `sup-handoff-abort` → the doctor-visible flag → per the skill, "*doctor flags the
abort until the operator clears `state/supervisor-handoff-aborted.json`*". **A human must
delete a file for the unattended tier to stop nagging** — and, having aborted, the old body
"resumes duty" at 300–500k context and will simply try again on the next beat, failing the
same way, forever, while its context keeps growing toward the compaction wall the band exists
to avoid.

Also unaddressed: **the beat vs. handoff race.** The scheduled beat has no idea a handoff is in
flight. It fires `fleet send supervisor "beat"` at an arbitrary instant — including the window
between `handoff-begin` and `handoff-complete`, when the old body is *supposed* to be doing
nothing but waiting. A fork-steer at that moment rotates the old body's sid mid-handoff, which
(a) breaks `sup-handoff-complete`'s claim check (`_require_claim_holder` @6937 — the old body
no longer matches the claim it is trying to transfer), and (b) leaves a HANDSHAKE'd successor
in limbo with no one able to complete or abort it. The successor then self-orphans at its 600s
backstop (lessons, M-A: "handoff abort window (T=300s) < successor self-orphan backstop (600s)
so the old side always adjudicates" — an ordering that only holds if the old side *can* still
adjudicate).

**Named fix.** The beat must be handoff-aware: `fleet beat` reads `supervisor/HANDSHAKE` (or
the C1 claim state) and **exits 0 without steering** while a handoff is in flight. And T must
be re-derived on the transient-daemon substrate (C5) before any unattended handoff is
specced — with the successor-backstop ordering re-verified against the new T, since the M-A
lesson says that ordering is load-bearing and was flagged once already as a "reviewer
inconsistency" that turned out to be deliberate. **Design question:** should an unattended
supervisor hand off *at all*, or should it `respawn`-fresh (no two-party sync, no timeout, no
abort flag) and re-derive from GOALS + JOURNAL + knowledge? The soul-files design says
re-derivation is exactly what the journal is for. Respawn has its own C1 problem, but it has no
300s window and no human-cleared flag — for an *unattended* tier that is a much better trade,
and the draft should argue it explicitly rather than inheriting the attended protocol by
default.

---

## M4 — MED: no authorized-release verb, no nonce lifecycle — the morning's incident class is not closed by anything in the draft

**Fresh evidence (manager, 2026-07-17):** the previous supervisor body (`--bg`, state=done)
held the claim with a fresh heartbeat; the operator authorized `claude stop`; the next
`sup-boot` returned **freeze** ("roster-gone but heartbeat fresh — daemon restart? (G9)") and
the manager had to `rm supervisor/INCARNATION` by hand.

**Receipt — neither a release verb nor a nonce exists:**

```
# grep -rn -i "nonce\|sup_release\|sup-release\|authorized_release" bin/fleet.py   # at c1277bd
(no matches)
```

The draft mentions the nonce only as inherited context ("a per-body nonce is the fix
candidate (logged in three-tier-command.md)") and says nothing about release. So, per the
brief's three questions:

- **Authorized release: absent.** `supervisor_claim_decision`'s freeze branch is correct *and*
  terminal — it cannot distinguish an operator-authorized stop from a daemon restart, because
  the *authorization was never recorded anywhere*. The information exists (a human decided);
  the system has no place to put it. **Fix:** `fleet sup-release [--reason]` — an operator verb
  that clears `INCARNATION` under `fleet.lock`, journals a `RELEASED` entry (new kind), and is
  the sanctioned alternative to `rm`. It costs ~20 lines and it converts a hand-`rm` (an
  unlogged, unauditable, error-prone act on a file the spec calls single-writer-under-lock)
  into a recorded transition. Note the current situation is worse than "no verb": the manual
  `rm` **bypasses `fleet.lock`**, which `write_incarnation`'s docstring @6445 declares mandatory
  ("Caller MUST hold fleet_lock (single-supervisor invariant, spec §4)") — the documented
  recovery procedure violates the invariant it is recovering.
- **Nonce lifecycle across respawn/handoff: unspecified.** The draft proposes a nonce without
  saying what writes it, what checks it, or at which boundaries — the brief's exact question,
  and the draft does not attempt it. My answer, offered as the delta to spec: the nonce is
  minted **by the body, in-session** (it must be — the whole point is discriminating two
  bodies fleet's own records cannot tell apart; anything fleet mints at dispatch is inherited
  by a `--fork-session` copy along with everything else), recorded into `INCARNATION` at
  `sup-boot` alongside the sid, and checked by `_require_claim_holder` **and** (per C2) by every
  mutating verb run from a supervisor-mode session. Boundaries where it must be re-minted:
  fresh boot, seize, handoff-complete (successor's own), and **every fork-steer** — i.e. every
  time the body's sid changes, which is C1's fix again.
  **The hard part the spec must confront:** a `--fork-session` zombie has the nonce in its
  *transcript*, so if the nonce is re-derived from context the zombie has it too. It must live
  somewhere the fork cannot inherit — process-local state (`CLAUDE_CODE_SESSION_ID` is
  per-session and stamped by claude itself, which is the one identity a fork *cannot* share,
  since a fork mints a new sid) is the only candidate I can see. **Which means: sid + a
  registry-mediated name→sid lookup may already be sufficient for the zombie class, and the
  nonce may be redundant** — the observed zombie shared a sid only because it was a *manager
  conversation* fork outside fleet's registry, not a fleet worker. That is worth resolving
  before spending a delta on nonce plumbing. **Design question for the spec author:** can a
  fleet-managed `--bg` body be `--fork-session`-forked at all? If not, the nonce buys nothing
  the registry doesn't; if yes, name the mechanism.
- **What a scheduled beat does when it fires into a freeze: undefined.** Per C1 this is the
  *normal* state, not an edge case. `sup-boot` returns rc 3 and the skill says page the
  operator — a scheduled task cannot page anyone (H3). **Fix:** `fleet beat` must treat freeze
  as "record the freeze in `events.jsonl`, stamp the run file, exit 0 without a model turn" —
  never "seize", never "retry", never a silent nothing.

---

## M5 — MED: "humans steer only via the interface tier" is doctrine with no mechanism, and the draft knows the doctrine already failed

**Draft says:**

> Doctrine needed: humans talk to the interface tier; direct `fleet send` to a claimed
> fleet's workers is an incident, not a convenience.

The two-manager incident (2026-07-16, in the draft's own hazard list) happened **with a human
who knew the doctrine** — the acting supervisor *was* the operator's counterpart and they still
double-steered. A rule that its own author violates on the day it is written is not a control.

**Failure scenario.** The operator, mid-conversation with the interface tier, sees a worker
stuck and types `fleet send mc-thing "try X"` in a terminal — the convenience path, one keystroke
cheaper than routing through the interface. The supervisor's next beat re-derives world state,
sees the worker moved, and cannot tell whether its own dispatch or a human's did it — because
`send` records no provenance distinguishable from the supervisor's own (both are `send`; per H4
a human shell's `caller` is `None`, and nothing in the mailbox records who sent what). Duplicate
scope, phantom steers, one husk blocked on a permission prompt — the observed outcome, replayed.

**Is a mechanical guard possible, and is it worth it?** Partially, and yes for the cheap half:

- **Cheap and worth it:** `fleet send` (and `spawn`/`kill`) can *notice*. The claim file says a
  supervisor exists and is fresh; the caller is a human shell (`caller is None`) or a session
  that is not the claim holder. Print a **warning** — "a supervisor holds this fleet
  (inc-A, heartbeat 3m); steering its workers directly is an incident (three-tier doctrine).
  Re-run with `--anyway` to proceed." — and require the flag. This is the `_confirm_destructive`
  pattern exactly (refuse-with-an-escape, no interactive prompt, agent must pass a flag), it
  reuses the file-only claim read the nag predicate already does, and it converts the doctrine
  into a speed bump at the one moment the human is about to violate it. It cannot stop a
  determined human, and it should not try.
- **Expensive and not worth it:** actually *blocking* a human. Fleet has always been a
  human-driven CLI (`_confirm_destructive`'s docstring makes this argument at length), the
  operator is the ultimate authority, and a lockout would be the first thing to fail during an
  incident — exactly when direct access matters most.
- **Free and worth it:** record it. `send` already writes `events.jsonl`; make the event carry
  the caller's provenance (sid or `human-shell`), so the supervisor's next beat can *see* that a
  foreign steer happened rather than being gaslit by its own registry. This closes the
  "phantom titles ≠ evidence" detection gap the M-C incident hit, and it costs one field.

**Design question:** which tier owns the incident *record* when a human steers directly? If the
supervisor is expected to notice and adapt, it needs the event field above. If the interface tier
is expected to confess ("I told the human not to"), that is doctrine again, and doctrine is what
just failed.

---

## L1 — LOW: "No new substrate" is not true, and the draft's cost estimate rests on it

**Draft says:**

> - No new substrate: durable sessions, mailbox, fork-steer, claim rituals, and the
>   scheduler bridge all shipped in M-B/M-C. The delta is one spawn verb, one
>   scheduled-task variant, and doctrine.

By this review's count the actual delta is: `sup-spawn`, `sup-release` (M4), `fleet beat` as a
first-class verb owning its own error semantics (H3), a claim identity that survives sid
rotation (C1), an archive/autoclean protection gate (C4), a rate-shaped budget (H2), a pending-
decision state file + its nag (H5), a POSIX scheduler seam or a ScheduleWakeup beat (M2), and a
roster-staleness axis in the epoch check (C5). That is a milestone, not "one spawn verb ...
and doctrine". The estimate is not merely optimistic — it is what would make an operator green-
light this as a small M-D slice, and the small-slice framing is how each of C1–C5 would arrive
in production untested. Re-scope honestly, then decide.

## L2 — LOW: the draft treats the AI-title hazard as cosmetic; it is the reason the incident took hours to detect

**Draft says:**

> (The agents-menu "requires input" nag on a RETIRED fork predecessor is a separate cosmetic
> bug worth filing.)

Agreed on the nag. But the neighboring fact — "AI-generated roster titles ≠ message text — do
not treat titles as evidence" — is load-bearing for the three-tier design specifically: the
interface tier's whole read surface is `sup-status --json` + journal tail, and the human's is
the agents menu. If the menu's titles are AI-generated fiction (lessons: "AI-generated roster
titles made them look foreign"), then **the human's only ambient view of the fleet is
untrustworthy by construction**, and the interface tier is the only thing standing between the
operator and a wrong mental model. That is an argument *for* the interface tier, and the draft
should make it rather than filing it as cosmetic.

---

## VERDICT: **restructure**

Not `reject` — the operator's model (thin conversational tier, disposable mechanical tier,
churning workers) is sound, the context economics are real, and roughly half the pieces exist.
Not `ratify-with-deltas` — the deltas are not additive. The draft's two structural choices
collide: **the supervisor cannot be an ordinary fleet worker while the claim is keyed on the
sid that fleet rotates every time it steers one** (C1), and **the claim cannot be the safety
mechanism while it gates only the journal** (C2). Those are foundations, and C3/C4/C5 each
independently kill an unattended supervisor in under 48h of wall-clock. A delta list on top of
this draft would be building on the collision.

The restructure I recommend, in one line: **split the beat from the supervisor** (H1's cheap
haiku beat worker that holds no claim and only decides "does a human-grade session need to
wake up?"), **key supervisor identity on something fleet does not rotate** (C1/M4), and
**make the beat a first-class `fleet beat` verb that owns freeze/limited/handoff/pending-
decision semantics** (H3/M3/H5/M4) rather than a raw `fleet send` in a scheduled task.

### MUST-fix before any spec/build task starts

1. **Resolve supervisor body identity.** (C1, M4) Name what identity survives fork-steer,
   respawn, and handoff; specify what writes it and what checks it, at which boundaries. No
   `sup-spawn` before this.
2. **Decide what the claim gates.** (C2) Journal-only (and then name the *other* mechanism that
   prevents a superseded body from acting — body-fencing via verified `claude stop` is the
   candidate), or extend the claim to mutating verbs for fleet-managed sessions. Silence here
   means the design ships the zombie class.
3. **Reconcile the beat period with `SUPERVISOR_CLAIM_STALE_SECONDS` and with the archiver.**
   (C3, C4) Heartbeat must decouple from the beat; the supervisor record must be
   archive/autoclean-protected as gate 0, by construction, not by TTL margin.
4. **Re-pin the substrate contract before speccing against it.** (C5) `md-contract`'s
   transient-daemon findings land in `docs/specs/native-substrate.md` first; the epoch check
   needs a staleness axis, because a stale roster passes it today and every claim decision and
   every `send` branch reads it.
5. **Answer beat economics with a mechanism, not a wish.** (H1, H2) `model` is spawn-immutable
   and `token_ceiling` is cumulative, so "cheapest-capable model for a beat" and "a bounded
   immortal supervisor" are both currently unimplementable. The beat-worker split is the
   cheapest answer to both; whatever is chosen, GOALS' "per-incarnation cap, beat-rate bound"
   must become real or be struck from GOALS.
6. **The scheduled command must be a fleet verb with its own error semantics and a run-stamp.**
   (H3, H4, M4) Not a bare `fleet send`. It must handle limited/freeze/handoff-in-flight/
   pending-decision without a model turn, stamp its run, and be the only thing
   `--supervisor-beat` will install. Bound what the scheduler is ever allowed to invoke —
   it runs with human authority and no guard.
7. **Give operator-gate routing a state file, not a journal kind.** (H5) A pending decision must
   be answerable, un-re-derivable, nag-visible, and must stop the beat from burning turns while
   it is open.
8. **Portability: spec the cron/launchd seam now, or build the beat on ScheduleWakeup.** (M2)
   Per the 2026-07-17 directive a new Windows-only feature is not an acceptable end state, and
   the schtasks 1..23 clamp forbids the long beats GOALS asks for. The draft must also
   reconcile with §12's existing ScheduleWakeup heartbeat primitive, which it never mentions.
9. **Drop event-driven from the design** (M1) — the draft's stated blocker is a misread of SPEC
   §8(a), and the real blockers (a hook cannot dispatch; the target sid rotates; a lost event is
   silent) make poll-on-beat strictly safer. Re-scope L1's "one spawn verb and doctrine"
   estimate to what this list actually implies before an operator green-lights the slice.

### Not blocking, worth doing in the same milestone

- `fleet send`/`spawn`/`kill` warn + `--anyway` when a fresh foreign claim exists; `events.jsonl`
  records caller provenance so the supervisor can see human steers instead of being gaslit
  (M5).
- File the agents-menu nag bug; move the AI-title hazard from "cosmetic" to "the reason the
  interface tier exists" (L2).

*Reviewer note (C4 lesson: a bare "no issues" is a failed review): every CRITICAL here is
reproducible from the receipts above by reading the quoted code paths in the order given —
`_restamp_after_steer` → `_require_claim_holder` → `supervisor_claim_decision` is the whole of
C1, and it needs no live fleet to see. No finding in this review depends on a claim I could not
receipt or quote.*
