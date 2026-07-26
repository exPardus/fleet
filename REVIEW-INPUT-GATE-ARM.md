# REVIEW INPUT — `gate-arm`

Branch `fix/gate-arm-released`, four commits on top of `main` @ `6b748fd`.
**Nothing pushed.** Brief: `state/tasks/briefs/gate-arm-lens.md`. Ruling:
`docs/AUTONOMOUS-2026-07-26.md` §R3.

| | |
|---|---|
| Verdict | **both tasks landed, in the ruling's order** |
| Commits | `859e2f5` (Task 1) → `11acca1` (Task 2) → `592c55e`, `39e918c` (test hardening) |
| Both floors | **2185 passed / 11 skipped** on `py -3.13` **and** `py -3.10` (baseline `2152/11`) |
| Mutation | **8 / 8 guards killed** (one required a new test to become killable) |
| Receipts | `claim-nonce.md` re-verified: `58/59 reproduce exactly, 0 failures, 1 warning` — the warning is a pre-existing volatile directory mtime at `:1357`, present before this branch |
| Defect minted | one, **caught before commit** — see §4 |

---

## 1. What changed and where

### Task 1 — arm the §7 gate on the wedged state (`859e2f5`)

| Site | Change |
|---|---|
| `bin/fleet.py:10135` | **new** `_releaser_is_roster_live(claim, live_sids, registry=None)` — the wedged state as ONE predicate |
| `bin/fleet.py:10264` | B6 (§6.1 rule 1) delegates to it — behaviour-identical at this commit |
| `bin/fleet.py:10581` | **new** `_wedged_release_gate(verb, claim)` — the gate's released arm |
| `bin/fleet.py:10704-10705` | `_supervisor_gate`'s unconditional `state == "released"` early-out replaced by a call to it |
| `bin/fleet.py:10639-10653` | the docstring's ARMING CONDITIONS table rewritten — the old text said *"no held claim / a released claim -> nothing to gate against"* |
| `docs/specs/claim-nonce.md` §7.2 | **new** subsection, `PROVISIONAL — RATIFICATION-WITHHELD` on §7.1's terms |
| `tests/test_gate_arm_wedge.py` | **new**, 21 tests |
| `tests/test_supervisor_gate.py:62,79` | the two existing released-claim tests narrowed and made deterministic (see §5.3) |

Shipped arming, all four arms tested:

| Released-claim state | gate |
|---|---|
| releaser roster-**gone** | disarmed |
| `released_by_sid` absent / empty / non-string | disarmed |
| roster unreadable (`roster_ok` false) | disarmed, **fail OPEN** |
| releaser roster-**LIVE** | **ARMED, unconditionally** |

The armed arm has **no `--nonce` path** and says so. §6.3's post-release key set
carries no `nonce_hash`, `pending_nonce_hash` or `prior_pending_hash`, so
`_nonce_presentation` returns `None` for every caller and every value. Offering
`--nonce` would be a named remedy that always fails — the exact defect R2 forbids.
The refusal names what actually ends the wedge: the releasing body exiting
(`cmd_sup_release` already orders it to), the operator stopping that session by the
sid printed, and §7's structural no-sid bypass.

### Task 2 — re-key B6 through the union (`11acca1`)

| Site | Change |
|---|---|
| `bin/fleet.py:10164-10171` | the union re-key, **inside the shared predicate** — so it fixes B6 *and* the §7 gate in one edit |
| `bin/fleet.py:10197,10203` | `supervisor_claim_decision` gains `registry=None`, alongside `holder_limited=` and for the same reason |
| `bin/fleet.py:10481` | `cmd_sup_boot` supplies it (under `fleet_lock`, where `_holder_is_limited` already reads) |
| `bin/fleet.py:10111` | **new** `_registry_records_or_none()` — the non-quarantining read, see §4 |
| `bin/fleet.py:10615` | the gate supplies it too |
| `docs/specs/claim-nonce.md:1583,1588,1595` | §6.1 rule-1 row and signature updated |
| `tests/test_b6_sid_union.py` | **new**, 12 tests |

Predicate: releaser is live if `released_by_sid` is in `live_sids`, **or** any record
whose `_record_sids` union carries it has a live sid. Additive — a live releaser sid
matching no record still refuses, so it can never regress the state the bare
comparison already caught. `registry=None` degrades to the bare comparison.

### Deliberately NOT changed

`_caller_holds_supervisor_claim` (`:2005`) and `_record_is_supervisor_claim_holder`
(`:2059`) keep their released early-out. **I could not demonstrate the wedged state
strips anything there, and the brief said not to widen on speculation.** The reasons
are executable, not asserted:

- `:2005`'s only consumer is `_ceiling_refuses_dispatch`, whose three call sites
  (`spawn :3380`, `send :4479`, `sup-spawn :11527`) all run **strictly after**
  `_supervisor_gate`. In the wedged state the gate refuses first and harder, so a
  dormant ceiling is unreachable. Pinned by
  `TestTheGateFiresAheadOfTheCeiling::test_a_wedged_spawn_is_refused_by_the_gate_not_the_ceiling`,
  which also asserts `dispatch_bg` is never reached.
- `:2059`'s archive consumer answers `False` for a released claim **by design** (B9:
  a released-away husk stays archivable). In the wedged state the releaser is by
  definition roster-live, and `_archive_eligible`'s gate 3 already refuses every
  roster-live record. Pinned by
  `TestArchiveProtectionIsNotStrippedByTheWedge`, which asserts the record is
  ineligible **and** that the reason is not gate 0.

---

## 2. RED → GREEN

### Task 1 — RED (before `859e2f5`, `py -3.13 -m pytest tests/test_gate_arm_wedge.py -q`)

```
8 failed, 11 passed in 62.15s
FAILED ...::test_clean_yes_from_a_third_body_is_refused_and_deletes_nothing
FAILED ...::test_the_other_two_measured_verbs_never_reach_their_work[kill-argv0-_cmd_kill_native]
FAILED ...::test_the_other_two_measured_verbs_never_reach_their_work[interrupt-argv1-_cmd_interrupt_native]
FAILED ...::test_the_releaser_body_itself_is_refused_too
FAILED ...::test_the_wedge_refusal_writes_nothing
FAILED ...::test_the_wedge_refusal_names_only_exits_that_execute
FAILED ...::test_presenting_a_generation_cannot_open_the_wedge
FAILED ...::test_a_wedged_spawn_is_refused_by_the_gate_not_the_ceiling
```

The headline failure, verbatim — councilor 4's live measurement reproduced in the suite:

```
E       AssertionError: assert 0 == 4
E        +  where 0 = fleet.main(['clean', '--yes'])
E        +  and   4 = fleet.SUPERVISOR_CONTINUITY_RC
```

`fleet clean --yes` **returned 0 and deleted the tombstone** from a third body, through
a wedged claim, on `main`.

Every negative arm (clean release, no-sid caller, unnamed releaser, unreadable roster)
was already green in RED — the 11 passes — so the 8 failures isolate the arming and
nothing else.

### Task 1 — GREEN (`859e2f5`)

```
tests/test_gate_arm_wedge.py .................. 19 passed in 3.97s
py -3.13 -m pytest -q --ignore=tests/test_b6_sid_union.py -> 2171 passed, 11 skipped
py -3.10 -m pytest -q --ignore=tests/test_b6_sid_union.py -> 2171 passed, 11 skipped
```

### Task 2 — RED (before `11acca1`, with Task 1 already shipped)

```
9 failed, 1 passed in 0.48s
FAILED ...::test_b6_refuses_when_the_releaser_sid_is_only_in_retired_sids
FAILED ...::test_the_gate_arms_through_the_union_too
FAILED ...::test_b6_still_claims_when_no_sid_of_the_record_is_live
FAILED ...::test_the_union_never_makes_one_body_answer_for_another
FAILED ...::test_a_bare_live_releaser_sid_still_refuses_without_any_registry
FAILED ...::test_the_shared_predicate_decides_both[live0-True] ... [live3-False]
```

### Task 2 — GREEN

```
tests/test_b6_sid_union.py .......... 10 passed
```

### Final, both floors, everything

```
py -3.13 -m pytest -q   ->  2185 passed, 11 skipped in 98.86s
py -3.10 -m pytest -q   ->  2185 passed, 11 skipped in 100.20s
```

Baseline on `main` was measured on this box before any edit: **2152 passed / 11 skipped
on both**. Net +33 tests, **zero pre-existing tests changed in outcome**; the only two
existing tests edited are documented in §5.3 and both still pass.

**Assertion discipline (trap 4).** Every arming test drives the last verb and asserts
its effect: `clean --yes` deletes nothing (`_names() == ["ghost"]`); `kill` and
`interrupt` never reach `_cmd_kill_native` / `_cmd_interrupt_native` and the victim
stays `idle`; `spawn` never reaches `dispatch_bg`; `sup-boot` leaves the claim
`released` with `incarnation_id` unchanged. Each is paired with a byte-identical
roster-gone control that must **succeed**, so no refusal can be passing for an
unrelated reason.

---

## 3. Mutation ratio — 8 / 8

Each guard broken in `bin/fleet.py`, the five relevant test files re-run, then restored.
Driver: `$CLAUDE_JOB_DIR/tmp/mutate.py`.

| # | Guard mutated | Result | First killer |
|---|---|---|---|
| M1 | released arm → old unconditional early return | **11 failed** | `test_clean_yes_from_a_third_body_is_refused_and_deletes_nothing` |
| M2 | `released_by` must be a non-empty string | **2 failed** | `test_a_released_record_naming_no_releaser_is_not_gated_by_a_None_in_the_roster[None]` |
| M3 | roster-unreadable fails OPEN | **1 failed** | `test_the_roster_ok_flag_is_what_disarms_not_the_payload_shape` |
| M4 | gate disarms on a clean release | **6 failed** | `test_the_same_two_verbs_run_once_the_releaser_is_gone[kill]` |
| M5 | sid-union re-key | **4 failed** | `test_b6_refuses_when_the_releaser_sid_is_only_in_retired_sids` |
| M6 | registry read does not quarantine | **1 failed** | `test_the_gate_never_quarantines_a_corrupt_registry` |
| M7 | B6 receives the registry | **3 failed** | `test_b6_refuses_when_the_releaser_sid_is_only_in_retired_sids` |
| M8 | `cmd_sup_boot` hands the registry over | **1 failed** | `test_sup_boot_itself_refuses_the_fork_steered_wedge` |

`git status --porcelain` after the run: **empty**.

**M3 survived the first pass and that is the interesting one.** With the shipped
contract, `roster_ok=False` means `payload` is a *reason string*; `_roster_live_sids`
iterating a string yields the empty set, so deleting the `not roster_ok` guard changed
nothing and the gate disarmed by the back door. A load-bearing guard that looks
redundant is an invitation to delete it. `39e918c` adds an arm that feeds an
**off-contract** payload (entries on a failed fetch — what a partial result or CLI
drift produces) and asserts the gate still disarms, so correctness rests on the flag
fleet checked rather than on `_roster_live_sids` happening to tolerate what came back.

**M8 was not killable when Task 2 first went green.** Every B6 test called
`supervisor_claim_decision` directly and supplied `registry=` itself, so all of them
stayed green with the one production call site dropping the argument — rule 1 would
have silently reverted to the fail-open comparison. `592c55e` adds
`test_sup_boot_itself_refuses_the_fork_steered_wedge`, which drives `fleet sup-boot`
and asserts the claim was not consumed. This is the same defect shape as trap 4 and I
only found it by running the mutation table.

---

## 4. The defect this wave minted, caught before it shipped

**fix-waves-mint-defects is 11/11 lifetime, and this wave was on track for 12.**

The obvious reader for the new registry access is `load_registry()`. I wrote it that
way. `load_registry` **quarantines** a corrupt registry — it renames the file aside
(`bin/fleet.py:812`) and appends an event. That is a **write**, from
`_supervisor_gate`, which documents itself *"READ-ONLY: no lock, no mint, no write"*
and runs at the top of **every** mutating verb. A speed-bump would have destroyed the
operator's only forensic copy of a corrupt registry while claiming to touch nothing.
It is the same hazard D4 (`bin/fleet.py:2574`) already names for the view path — *"a
10s-refresh loop would shred operator evidence"* — one reader over.

Caught by reading `load_registry`'s body before trusting its name. Fixed by
`_registry_records_or_none()` → `_read_registry_readonly()`, pinned by
`test_the_gate_never_quarantines_a_corrupt_registry`, which writes real corruption to
disk and asserts no `fleet.json.corrupt.*` appears. Mutant M6 confirms the pin bites.

Quarantining stays where it belongs — the lock-holding verbs, `cmd_sup_boot` included
via `_holder_is_limited`, which is unchanged.

**A second, smaller one, also caught before commit:** my first RED run of the ceiling
test drove `fleet spawn` all the way through a disarmed gate and **launched four real
background `claude` sessions** into pytest tmp dirs. I found them in the roster and
stopped all four by short id; they read `state: stopped` with no `pid`/`status`. The
test now stubs `dispatch_bg` with a `pytest.fail`, so it can never dispatch again. The
incident is itself evidence for the finding: with the gate disarmed, `spawn` from a
third body really does reach a real, billable session.

---

## 5. Push back on this

Ordered by how much I want a reviewer to attack them.

### 5.1 The wedge now refuses **every** mutating verb, fleet-wide, with no timer — and I think that is the strongest objection to my own work

The ruling asked for containment and I built it fail-closed, as ordered. Read the cost
honestly:

- Under a held claim the gate is bounded twice — the supervisor can present `--nonce`,
  and the whole thing disarms after `SUPERVISOR_CLAIM_STALE_SECONDS`.
- Under a wedge **neither bound exists.** There is no generation to present (§6.3) and
  no `heartbeat_at` to age. The only exit is the releasing body leaving the roster.

So for as long as a released supervisor's session lingers, every sid-bearing caller on
this box is refused `spawn`, `send`, `kill`, `clean`, `interrupt`, `respawn`,
`archive`, `resume-limited`, `release` and `init`. That includes `resume-limited`, a
recovery verb, and `send`, the beat contract's hot path. Councilor 4 sized this at
"~10 lines"; the lines are cheap and the *semantics* are not.

I still think it is right — the alternative is the ungated `clean --yes` that is live
on `main` today, and the normal case self-heals in seconds because `cmd_sup_release`
tells the body to exit. But a reviewer should ask whether the exit ramp is enough.
Three things I considered and rejected, each of which a reviewer may reinstate:

1. **A carve-out for `send` to the releaser's own record.** Today a wedge refuses the
   very message that could tell the lingering body to exit. §7.1's existing carve-out
   does not extend, because `_resolve_worker_target("supervisor")` raises on a released
   claim before the gate is reached. I left it out because the brief said do not widen
   and because the operator lever (stop the session by sid) is more reliable than
   asking a wedged body nicely. **This is the change I would make first if the
   refusal turns out to bite in practice.**
2. **A staleness bound on `released_at`.** A wedge older than N hours could disarm, on
   the theory that a body lingering that long is a husk. I did not build it: unlike a
   heartbeat, `released_at` measures nothing about the releaser's liveness, and the
   roster already answers that question directly.
3. **Escalating rather than refusing** — let the verb run but page. Rejected: the state
   this exists to contain is `clean --yes`, and a page after an irreversible deletion
   is a receipt, not a control.

### 5.2 Fail-open on an unreadable roster is a real hole and I chose it on consistency, not on evidence

If `claude` is missing from `PATH`, or the roster subprocess times out, the gate
disarms and the wedge is ungated again. I matched the unreadable-heartbeat rule in the
same function (*"a speed-bump must not brick every mutating verb"*), and the blast
radius of the alternative is larger: fail-closed means every mutating verb dies for as
long as a released claim sits on disk **and** the roster is unreadable.

But note the shape — **`_cmd_respawn_supervisor`'s caller-side B6 gate at `:6059-6063`
does the opposite**, `if not roster_ok: return True`, i.e. fail toward the gate. Two
guards keyed on the same question now disagree about the unreadable case. I think the
difference is defensible (that one is a caller gating *itself* before a destructive
step; this one is a speed-bump on every verb), but a reviewer who thinks the fleet
should have one rule here has a good argument and I would not fight it hard.

### 5.3 I edited two existing tests, and one of them lost coverage that nobody replaced in the same file

`tests/test_supervisor_gate.py:62` was `test_a_released_claim_disarms_the_gate`. That
name asserted the exact behaviour this branch deletes, so I renamed it
`test_a_CLEANLY_released_claim_disarms_the_gate` and stubbed the roster. Both edits
are defensible individually:

- The rename is the honest one — "released disarms" is no longer true.
- The roster stub is a **bug fix in the test**: without it the test was passing only
  because the developer's live roster happens not to list `sid-x`. It called the real
  `claude agents --json --all` and its outcome depended on who ran it. Same for
  `:69`.

The pushback: a reviewer reading `test_supervisor_gate.py` alone now sees no wedged
case at all — it lives in a different file. If you think the arming matrix should stay
in one place, move `TestTheWedgedStateArmsTheGate` into `test_supervisor_gate.py`.

### 5.4 I added a `PROVISIONAL` subsection to an OPERATOR-OWNED spec section

`docs/specs/claim-nonce.md` §7 is operator-owned; only Altai ratifies. I wrote §7.2
anyway, marked `RATIFICATION-WITHHELD` on §7.1's exact terms, because R3's closing
section says this project's characteristic failure is shipping a guard whose rule is
not written down — and a new arming condition that exists only in a docstring is that
failure. The ruling itself calls the change *"fail-closed, no protocol change"* and
ticks no box in `OPERATOR-GATES.md`, and I touched neither `OPERATOR-GATES.md` nor
`supervisor/GOALS.md`.

A reviewer may still hold that **narrowing a disarm condition is a taxonomy change**
and that even a provisional subsection is the operator's to write. If so, the fix is
to delete §7.2 and file it as an operator gate; the code and tests stand without it.

### 5.5 Two costs I introduced that are real and are not in the ruling

- **The gate now shells out.** `_wedged_release_gate` runs `claude agents --json --all`
  (~1.7 s measured on this box; `_fetch_agents_roster`'s timeout is 30 s). It is the
  only IO in the gate and is reached **only** on a released claim naming a releaser —
  a held claim, an absent claim and a no-sid caller never fetch it, pinned by
  `test_the_roster_is_not_fetched_when_the_claim_is_not_released`. But in the
  release→boot window, `clean` and `respawn` now fetch the roster **twice** (gate +
  their own), and the gate has no `which=`/`run=` injection, so a test that injects a
  fake `run` into `cmd_kill` does not reach it.
- **`_supervisor_gate`'s existing `send` carve-out at `:10653` already calls
  `load_registry()`** — the quarantining reader — inside a function documented "no
  write". That is pre-existing, not mine, and §4's argument applies to it verbatim. I
  did not touch it: it is outside this brief's scope and changing a ratified §7.1
  predicate on my own initiative is exactly the widening I was told not to do. **It
  should be filed.**

### 5.6 A pre-existing hole this work put in front of me but did not close

`fleet autoclean` from a sid-bearing caller has its archive tier refused by the gate
(tier isolation catches it and records an error), while `_sweep_husks` and
`_expire_tombstones` — which delete files — are not gated at all. That is true today
under a held claim and is unchanged by this branch; §7's taxonomy lists `autoclean` as
a mutating lifecycle verb while the design treats it as structurally exempt, and the
two readings do not agree. I pinned the scheduled no-sid path so this branch cannot
have silently regressed it (`test_scheduled_autoclean_still_runs_under_a_wedge`), and
left the discrepancy alone.

### 5.7 One thing in the brief I checked rather than believed

Trap 5 says do not "fix" `docs/SPEC.md:334`. I did not touch it, and I did not
re-litigate it either — two agents have already falsified that claim and a third
re-derivation is the *"claim that gained authority in transit"* pattern R4 names. I
mention it only so the reviewer knows the omission is deliberate.

---

## 6. Fences

| Fence | Status |
|---|---|
| No push of ANY ref | **held** — four local commits, no `push`, no remote touched |
| No merge, no rebase | **held** |
| No `sup-*` verb of any kind | **held** |
| No daemon restart | **held** |
| No other worker's worktree | **held** — only `C:/proga/fleet-gate-arm` |
| `supervisor/GOALS.md`, `docs/OPERATOR-GATES.md` untouched | **held** |
| No `--interface`, no attestation surface | **held** — nothing imported from `fix/b6-interface-release` |
| Never author `state/tasks/gate-arm.md` | **held** — scratch in `$CLAUDE_JOB_DIR/tmp` |
| `docs/SPEC.md:334` untouched | **held** |

One action worth declaring: I ran `claude stop` on **four** background sessions —
`a7434716`, `e949e65b`, `3f6f2b78`, `8cef32b7` — all `fleet|w|go` in
`pytest-of-Techn/*/test_a_wedged_spawn_is_refused0`, all spawned by my own RED run
minutes earlier (§4). No other session was touched and no daemon was restarted.
