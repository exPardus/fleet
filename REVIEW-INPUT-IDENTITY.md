# REVIEW INPUT — the registry judges fleet identity; the environment only witnesses

Branch `fix/identity-registry-judges`, off `main` @ `8dee4b8`.
Builder: fleet worker `id-build`, 2026-07-26.

**Read §9 first if you read nothing else.** It lists the three places where I departed from the
brief and the one place where I believe the brief is factually wrong. The project's record says a
builder's own flagged judgment call is where the next defect lives, so they are collected rather
than scattered.

---

## 1. What shipped

| Commit | Contents |
|---|---|
| `2878c68` | `bin/fleet.py` re-key + `tests/test_identity_registry.py` (new, 57 tests) + collateral test updates |
| (this commit) | `docs/specs/claim-nonce.md` §16 amendment, this report, two doctor-row wording fixes |

Suite, **both floors**: `2152 passed / 11 skipped` on `main` → `2215 passed / 11 skipped` on the
branch. No net loss; the 11 skips are untouched (5 `FLEET_LIVE=1` live tier, 2 platform-complementary
partial-write pair, 4 others).

---

## 2. The diff, function by function

### 2.1 New — `_acting_worker_identity(sid=None, registry=None) -> dict` (`bin/fleet.py:2114`)

The single place that answers *"which fleet worker am I?"*. Resolves the acting session's own
`CLAUDE_CODE_SESSION_ID` against every registry record's sid **union** (`_record_sids` = `session_id`
∪ `retired_sids`), never the bare `session_id` — a sid rotates on fork-steer and respawn, and the
union is the same bridge `_caller_holds_supervisor_claim` already uses (ND4a).

Returns `{"verdict", "name", "record", "matches", "sid"}` with three verdicts
(`IDENTITY_RESOLVED` / `IDENTITY_UNRESOLVED` / `IDENTITY_AMBIGUOUS`).

Candidate selection: `candidates = live_matches or all_matches`, resolved iff exactly one.
`_record_is_live` = not archived and `status != "dead"`. So a dead or archived husk sharing a sid
with a live record does **not** manufacture ambiguity, while two husks and no live record still
refuse to guess.

Never raises. A corrupt/unreadable registry degrades to UNRESOLVED.

Thin wrappers `_acting_worker_name()` and `_acting_worker_record()` return `None` on either
abstention — the brief's requested names.

### 2.2 Site A — `_ceiling_refuses_dispatch` (`bin/fleet.py:~2280`)

```
BEFORE                                          AFTER
if not (os.environ.get("FLEET_WORKER")          caller = current_caller_session()
        or "").strip():                         if caller is None:
    return None                                     return None
caller = current_caller_session()               holds = _caller_holds_supervisor_claim(caller)
if caller is None:                              if holds is False:
    return None                                     return None
if _caller_holds_supervisor_claim(              if holds is not True and \
        caller) is False:                              _acting_worker_name(sid=caller) is None:
    return None                                     return None
```

**The new predicate for the structural exemption (c): "no registry record claims my sid, AND I am
not the claim-holder."** The `and not the claim-holder` conjunct is what stops it being a loophole —
a body the *claim* names as holder is subject to the ceiling whether or not the registry has caught
up with it (the stranded-stamp window).

Ordering: (c) can no longer literally precede all sid work, because it *is* sid work. The property
that ordering existed to protect is preserved by construction — the human channel has no sid at all
(exempt at `caller is None`), and the interface session either resolves to `holds is False` (exempt)
or to UNRESOLVED-and-not-holder (exempt). Both are pinned:
`TestSiteACeiling::test_the_interface_session_is_still_exempt` and
`::test_the_interface_is_exempt_even_with_an_empty_registry`.

**Docstring claim downgraded, as the brief required.** The old text said occupancy is resolved from
*"the sid guaranteed fresh for the acting body"*. That guarantee is not proven and the docstring now
says so, replacing it with what is actually known: the sid read here is the same one every other
identity surface in the file reads, so a donated sid would mis-measure *consistently* rather than
inconsistently.

### 2.3 Site B — `_require_claim_holder` (`bin/fleet.py:~11150`)

```
BEFORE                                          AFTER
worker = os.environ.get("FLEET_WORKER")         role = _acting_worker_name()
if worker and worker.strip() and \              if role is not None and \
        not _is_supervisor_shaped(worker):              _is_supervisor_shaped(role):
    raise FleetCliError(...)   # a GATE             role = None
claim = read_incarnation()                      claim = read_incarnation()
                                                # ... nonce validation, rules 1-4 ...
                                                elif role is not None:     # rule 5, RECLASSIFIED
                                                    _append_nonce_rejection("worker-turn", ...)
                                                    raise FleetCliError(...)
                                                else:
                                                    _append_nonce_rejection("refused", ...)
                                                    raise _continuity_refusal(verb, claim)
```

Two changes, and **the second is the one that needs your attention**:

1. **Re-keyed** onto the registry.
2. **Demoted from gate to classifier.** The role verdict no longer decides *whether* a caller is
   refused — only *how* an already-certain refusal is worded, exit-coded and logged. See §5.

`_is_supervisor_shaped` still exempts the `sup|<inc>|<role>` family from the role verdict. The
E(2) grounding for that exemption survives the re-key untouched: it was always about who can *mint*
such a name (`NAME_RE` is `^[a-z0-9-]+$` and forbids `|`), never about where the name is read from.

New shared helper `_worker_turn_note(role)` (`:11060`) produces the note, so the no-claim refusal and
the rule-5 refusal cannot drift apart.

### 2.4 The write at `:1463` — KEPT

`env["FLEET_WORKER"] = name` is untouched. Its docstring was rewritten because it justified the
stamp by a SessionStart hook that no longer exists (terminal-surface D7, 2026-07-22 — that staleness
was pre-existing on `main`). It now states the only reason the stamp survives: it is the witness
`_doctor_check_identity_witness` checks the registry against, and deleting the write would delete
the only evidence of the leak.

### 2.5 New doctor row — `_doctor_check_identity_witness(workers)` (`bin/fleet.py:~8170`)

Wired into `cmd_doctor` after `orphaned-claims`, taking the `workers` dict already snapshotted under
`fleet_lock` — so the row performs **no second registry read and cannot quarantine anything**.
Exact text in §7.

### 2.6 Hooks — confirmed untouched, as instructed

```
$ grep -rn "FLEET_WORKER" bin/hooks/
(no matches)
```
Re-confirmed empirically. The hooks resolve workers by `session_id` from the hook payload. Nothing
was changed there. (`docs/superpowers/plans/2026-07-09-terminal-surface.md:1201` contains an
`os.environ.get("FLEET_WORKER")` — that is a *plan document* describing the deleted SessionStart
hook, not live code.)

### 2.7 The structural pin

`os.environ.get("FLEET_WORKER")` now occurs **exactly once** in `bin/fleet.py`, inside the doctor
row. `TestTheWitnessIsStillWritten::test_FLEET_WORKER_is_no_longer_a_predicate_anywhere` asserts the
count is 1, so re-introducing a second read is loud rather than silent.

---

## 3. UNRESOLVED, AMBIGUOUS, and the dispatch-window trap

| Path | Site A (ceiling) | Site B (`_require_claim_holder`) | Doctor |
|---|---|---|---|
| RESOLVED, supervisor-shaped | ceiling applies if holder | no role claimed → nonce decides | compared to witness |
| RESOLVED, worker-shaped | ceiling applies if holder | role claimed → *classifies* a nonce refusal | compared to witness |
| **UNRESOLVED** | **exempt** (unless claim-holder) | **pass through to the nonce** | **NOTE, never FAIL** |
| **AMBIGUOUS** | **exempt** (unless claim-holder) | **pass through to the nonce** | **FAIL, distinct wording** |

**The dispatch window (brief §4).** `cmd_sup_spawn` and the worker spawn path call
`new_worker_record(session_id=None, ...)` and fill the sid in ~60 lines later, once the dispatch
returns it. A legitimately-new body therefore has no sid-matching record during its own first
moments. Verified live in this tree: `grep -n "rec\[\"session_id\"\] = "` shows the fills at
`:3440/:3516/:5054/:11602/:11639/:12085`, all guarded by
`if rec is not None and rec.get("session_id") is None:` arms.

Pinned by:

| Behaviour | Test |
|---|---|
| the window itself is UNRESOLVED | `TestActingWorkerIdentity::test_the_dispatch_window_newborn_is_unresolved` |
| a `session_id=None` record never matches a sid-less caller | `::test_a_null_session_id_never_matches_a_null_sid` |
| Site A exempts the newborn | `TestSiteACeiling::test_the_dispatch_window_newborn_is_exempt` |
| Site A exempts an ambiguous body too | `::test_an_ambiguous_identity_is_exempt_like_an_unresolved_one` |
| Site A does **not** exempt an unresolved **claim-holder** | `::test_an_unresolved_body_that_IS_the_claim_holder_is_NOT_exempt` |
| Site B passes UNRESOLVED to the nonce (valid nonce ⇒ 0) | `TestInferenceNeverRefuses::test_an_unresolved_body_passes_through_to_the_nonce` |
| …and to the nonce, not *around* it (bad nonce ⇒ continuity refusal) | `::test_an_unresolved_body_WITHOUT_the_nonce_still_faces_continuity` |
| Site B passes AMBIGUOUS to the nonce | `::test_an_ambiguous_body_passes_through_to_the_nonce` |
| a newborn is never *called* a worker | `TestTheRoleClassifier::test_an_unresolved_body_is_never_classified_as_a_worker` |
| ambiguity never takes the first match | `TestAmbiguityIsItsOwnVerdict::test_ambiguity_never_silently_takes_the_first_match` |
| a dead/archived husk does not create ambiguity | `::test_a_dead_husk_sharing_the_sid_does_not_make_it_ambiguous`, `::test_an_archived_record_sharing_the_sid_does_not_make_it_ambiguous` |
| two husks and no live record still refuse to guess | `::test_two_dead_records_are_still_ambiguous_not_arbitrary` |

---

## 4. The §1 receipt, encoded as a regression test

`TestTheReceipt` constructs the measured disagreement — env `FLEET_WORKER` names record **X**
(`sup|inc-20260726T140146Z-5a0e|boot`, idle) while the acting sid
(`108300de-8d43-411e-8177-94843bee05ab`) belongs to record **Y**
(`sup|inc-20260726T164152Z-8180|boot`, working) — and asserts every read site answers **Y**:

- `test_the_helper_answers_Y_not_the_env_X`
- `test_site_A_the_ceiling_judges_by_the_registry_not_the_env`
- `test_site_B_does_not_refuse_the_body_the_env_slanders`

Mutation **M6** (re-key Site B back onto `FLEET_WORKER`) kills 23 tests; mutation **M4** (re-key
Site A back) kills 4. Neither site can be reverted quietly.

---

## 5. The §5 invariant: where it is enforced, and what dies if it is removed

> **An identity inference derived from the environment may never be the sole basis of a refusal.
> The nonce and the claim refuse; inference may only inform and announce.**

**Site A** satisfies it by *direction of travel*: the inference there only ever **exempts**. The
refusal's sole basis remains the measured occupancy of the acting transcript; identity only selects
whose transcript to measure. A misidentification at Site A can only make the ceiling fail to fire —
never fire wrongly.

**Site B** satisfies it by *ordering*. The role branch sits **after** the four nonce-validation arms,
so it is reached only when the nonce has already refused. What the role verdict changes:

| | continuity refusal | role reclassification |
|---|---|---|
| exception | `SupervisorContinuityError` | `FleetCliError` |
| exit code | 4 ("a second body of your lineage may be acting") | 1 (a role error) |
| log kind | `refused` → `_doctor_check_supervisor_claim` FAILs | `worker-turn` → doctor stays PASS |
| wording | "STOP, escalate" | "you are worker `w1`" |

**The test that dies if the invariant is removed:** mutation **M7** re-promotes the classifier to a
gate (raises immediately after `role` is computed, before the nonce is read) and kills

- `TestInferenceNeverRefuses::test_a_worker_shaped_identity_holding_the_live_nonce_is_NOT_refused`
- `TestWorkerTurnsCannotHoldTheClaim::test_a_worker_turn_HOLDING_the_live_generation_is_NOT_refused`
- `TestTheRoleClassifier::test_the_role_refusal_is_not_logged_as_a_continuity_refusal`

The first of those is the invariant's load-bearing pin, and it is also the §6 answer (below): a body
the registry judges to be an ordinary worker, presenting the live generation, **succeeds**.

**Uniqueness** (the second §5 requirement) is enforced in `_acting_worker_identity`'s
`len(candidates) == 1` and killed by mutation **M2** (5 tests).

---

## 6. The honest §6 answer — what breaks under hypothesis (ii)

Hypothesis (ii) is that the vendor passes the daemon's environment through, so
`CLAUDE_CODE_SESSION_ID` can be donated exactly as `FLEET_WORKER` demonstrably is. I did not run the
experiment that would decide it (the brief forbids it; the live daemon at pid 28812 was not touched,
no `claude daemon stop`, no lock deletion).

**Nothing in this build breaks under (ii), because inference never refuses.**

The property-by-property answer:

| Property | Under (ii) |
|---|---|
| A legitimate claim-holder can always reach `sup-release` / `sup-checkpoint` / `sup-heartbeat` | **HOLDS.** Its nonce is valid; the role verdict cannot refuse it. |
| The role classifier names the right worker | **BREAKS** — it would name the donor. Cost: wrong *words* on a refusal that was already certain, and a wrong `worker-turn` log line. |
| The doctor row names the right record | **BREAKS** — it would compare a donated witness against a donated sid, and could go quiet (both agreeing on the donor) or accuse the wrong record. Cost: a wrong *announcement*. |
| The 200k ceiling measures the right transcript | **BREAKS** — it would measure the donor's occupancy. Pre-existing: `_ceiling_refuses_dispatch` read the same sid before this change, so (ii) has always broken it. Cost: a wrong *measurement*, which can produce a wrong ceiling refusal — see the caveat below. |
| Any claim verb wrongly refused *because of identity* | **NONE.** |

**The one caveat I will not paper over.** The ceiling refusal is not purely occupancy-based: under
(ii) a supervisor could be measured against a donor's transcript and refused `spawn`/`send` for
occupancy that is not its own. That hazard is **inherited, not introduced** — `_ceiling_refuses_dispatch`
resolved occupancy from `current_caller_session()` before this branch and still does; my change did
not add a sid read to that path. It also has an operator escape (`sup-handoff-begin` is exempt from
the refusal), which the claim verbs did not. I am reporting it rather than claiming the invariant
makes the whole file safe: it makes **this build's new refusal surface** safe, and the ceiling's
pre-existing dependence on the sid is untouched.

**The test that pins the §6 answer:**
`TestInferenceNeverRefuses::test_a_worker_shaped_identity_holding_the_live_nonce_is_NOT_refused` —
the acting sid resolves to an ordinary worker record `some-worker` (exactly what a donated sid would
produce), and `cmd_sup_checkpoint` with the live generation returns `0`. Plus
`::test_the_wedged_supervisor_can_still_RELEASE`, which asserts the **end state** (`read_incarnation()
["state"] == "released"`), not merely that the verb was reachable.

---

## 7. The new doctor row — exact text, and what an operator does

Row name: **`identity-witness`**. Five outcomes, verbatim from the shipped code:

**(a) The leak — FAIL.** Witness names a record; the acting sid resolves to a different one.

```
[FAIL] identity-witness: LEAK: the FLEET_WORKER witness names a DIFFERENT record than this
session's own id resolves to. Witness: 'hs-fix2' (a registry record, status idle). Registry
verdict for my sid '108300de-8d43-411e-8177-94843bee05ab': 'sup|inc-20260726T164152Z-8180|boot'.
The registry is the judge and 'sup|inc-20260726T164152Z-8180|boot' is who this session is. The
stamp comes from the machine-wide `claude` daemon, which donates the environment of whichever
`--bg` dispatch started it to every session it hosts afterwards. Fleet cannot fix it from inside
a hosted session: let the daemon idle-exit (no `--bg` sessions alive) so the next dispatch starts
a fresh one, or ensure the supervisor's own dispatch is the one that starts it. Nothing in fleet
keys a decision on this variable, so an unfixed leak costs accuracy in this row and nothing else
```

**(b) The leak, witness naming nothing — FAIL.** Same row, with
`Witness: 'long-since-cleaned' (no registry record of that name).`

**(c) Ambiguity — FAIL, deliberately different wording** (it is a different fault with a different
remedy, and the operator must be able to tell them apart):

```
[FAIL] identity-witness: AMBIGUOUS identity: session id 'sid-dup' is carried by 2 registry
records ('dup-one', 'dup-two'). One session cannot be two workers, so at least one record's sid
union is wrong -- fleet abstains from judging this body's identity until it is resolved (no verb
is refused because of it). Inspect those records in state/fleet.json and retire the stale one
(`fleet clean`, or edit the registry out of band). FLEET_WORKER witness: 'dup-one'
```

**(d) Unresolved — PASS with a NOTE** (this is the dispatch window; failing here would make doctor
red for a transient, legitimate state):

```
[PASS] identity-witness: NOTE: FLEET_WORKER='some-worker' but no registry record claims this
session's own id ('sid-newborn'), so the witness cannot be checked against anything. Expected
during a body's own dispatch window (the record is written before the session exists and the sid
is filled in when the dispatch returns), and expected for any session fleet did not launch. If it
persists for a body that IS fleet-launched, the record's sid was never filled in -- inspect
state/fleet.json. <same daemon remedy text as (a)>
```

**(e) Agreement / no witness — PASS.**
`the FLEET_WORKER witness agrees with the registry (both name 'w1' for sid 'sid-w1')` /
`no FLEET_WORKER stamp in this environment; registry verdict for sid 'sid-w1': resolved ('w1')`

### What an operator does on (a)

1. **Nothing is broken by it.** The row says so explicitly, because the first instinct on a red
   doctor row is to stop working. No fleet decision keys on the variable any more; the leak costs
   accuracy in this row and nothing else.
2. **To clear it:** let the machine-wide daemon idle-exit — it must have no `--bg` sessions alive,
   which in practice means the fleet is quiet — so the next dispatch starts a fresh one. Or arrange
   for the supervisor's own dispatch to be the one that starts the daemon, so the donated stamp is
   at least supervisor-shaped and names the right lineage.
3. **What not to do:** killing the daemon or deleting `~/.claude/daemon.lock` kills every live
   session, supervisor included. The row deliberately does not name that lever.

---

## 8. Mutate → RED → restore ledger

Every row: commit first (`2878c68`), inject one deliberate breakage into `bin/fleet.py`, run
`tests/test_identity_registry.py tests/test_supervisor.py tests/test_supervisor_ceiling.py
tests/test_native.py tests/test_destructive_guard.py tests/test_cli.py` (1034 tests), then
`git checkout -- bin/fleet.py` and print `git status --porcelain`. Restore proof is **EMPTY** —
never a sha or byte comparison, because `core.autocrlf=true` on this machine makes those lie.
Driver: `$CLAUDE_JOB_DIR/tmp/mutate.py`.

| # | Guard mutated | Dead | Named victim (first) | Restore |
|---|---|---|---|---|
| M1 | helper: sid **union** → bare `session_id` | 3 | `TestActingWorkerIdentity::test_the_union_is_the_key_not_the_bare_session_id` | EMPTY |
| M2 | helper: refuse-to-guess → take first match | 5 | `TestAmbiguityIsItsOwnVerdict::test_ambiguity_never_silently_takes_the_first_match` | EMPTY |
| M3 | helper: live filter → every record is live | 2 | `TestAmbiguityIsItsOwnVerdict::test_a_dead_husk_sharing_the_sid_does_not_make_it_ambiguous` | EMPTY |
| M4 | **Site A** re-key → back onto `FLEET_WORKER` | 4 | `TestSiteACeiling::test_an_absent_FLEET_WORKER_no_longer_exempts_the_holder` | EMPTY |
| M5 | **Site A** drop `and not the claim-holder` | 6 | `TestSiteACeiling::test_an_unresolved_body_that_IS_the_claim_holder_is_NOT_exempt` (+5 pre-existing ceiling tests) | EMPTY |
| M6 | **Site B** re-key → back onto `FLEET_WORKER` | 23 | `TestTheRoleClassifier::test_the_name_comes_from_the_registry_not_the_environment` | EMPTY |
| M7 | **Site B** classifier → gate (**the §5 invariant**) | 3 | `TestInferenceNeverRefuses::test_a_worker_shaped_identity_holding_the_live_nonce_is_NOT_refused` | EMPTY |
| M8 | **Site B** drop the supervisor-shape exemption | 3 | `TestWorkerTurnsCannotHoldTheClaim::test_the_successor_still_faces_the_continuity_check` | EMPTY |
| M9 | **Site B** log kind `worker-turn` → `refused` | 1 | `TestTheRoleClassifier::test_the_role_refusal_is_not_logged_as_a_continuity_refusal` | EMPTY |
| M10 | doctor: leak row FAIL → always PASS | 3 | `TestDoctorAnnouncesTheLeak::test_a_disagreeing_witness_FAILS_and_names_both_records` | EMPTY |
| M11 | doctor: unwire the row from `cmd_doctor` | 1 | `TestDoctorAnnouncesTheLeak::test_the_check_is_wired_into_fleet_doctor` | EMPTY |
| M12 | witness: delete the `FLEET_WORKER` write | 4 | `TestTheWitnessIsStillWritten::test_worker_env_still_stamps_FLEET_WORKER` (+ `test_native`, `test_supervisor::TestHandoff`, `test_destructive_guard`) | EMPTY |

`final git status --porcelain: EMPTY`. **No guard came back green — every one of the twelve is
covered.**

---

## 9. Deviations and disagreements — read this section

### 9.1 DEVIATION (major): Site B's inference does not refuse at all

The brief's §3 table says "re-key to the registry" and §4 specifies only the UNRESOLVED path, which
reads as "RESOLVED-to-a-worker still refuses". **I did not build that.** §5's invariant and §6's
prompt ("if the honest answer is *none, because inference never refuses*, say that and show the test
that pins it") both require the opposite, and the two cannot be reconciled: a refusal keyed on a
registry lookup of a possibly-donated sid *is* an environment-derived inference refusing.

Concretely, if the refusal had survived: under hypothesis (ii) a legitimate supervisor whose sid was
donated from worker `W` resolves to `W`'s record, is provably not the claim-holder, and is refused —
which is the §1 wedge relocated one level down, not cured.

So the arm became a classifier. **What that costs:** a worker turn that has somehow been *given* the
live nonce is no longer stopped. The shipped arm's own message called itself *"a speed-bump, not a
security boundary"* and `env -u FLEET_WORKER` defeated it, so nothing that functioned as a control
was traded away — but this is a real behaviour reduction and it is the single most likely place for
you to disagree with me. It is also called out in the claim-nonce §16.3 amendment as the item most
in need of ratification.

### 9.2 DEVIATION (moderate): ND4b is narrowed, and one pre-existing test changed meaning

`test_supervisor_ceiling.py::TestCeiling::test_indeterminate_identity_fails_toward_band` failed
against the new predicate, and I rewrote it rather than weakening the design.

ND4b said an unresolvable identity fails **toward the band**. The brief's §4 says UNRESOLVED at Site
A ⇒ **exempt**. These are different senses of "unresolvable" that used to be independent and now
overlap, so I had to choose:

- A body the registry **can** place, whose *holder-ness* is merely indeterminate → **still fails
  toward the band.** ND4b preserved. (Reachable shape: a claim carrying no readable holder sid. Once
  the registry places the caller, "holder sid in no record" resolves to a definite `False`, not
  `None` — I verified this and added `assert fleet._caller_holds_supervisor_claim(...) is None` to
  the test so the setup cannot silently stop exercising the arm.)
- A body the registry **cannot place at all** → **exempt.** It is the interface, a human shell, or a
  body inside its own dispatch window, and a newborn body cannot be at 200k tokens.

New test `::test_an_unplaceable_sid_is_exempt_rather_than_failing_toward_band` states the trade
explicitly rather than leaving it implied.

Also rewritten: `::test_interface_is_exempt_even_over_ceiling`, whose setup gave the interface the
**holder's own sid** — a shape the fleet cannot produce (the interface is a human's session; the
holder is a `--bg` body), and one the old env-keyed predicate never looked at. It is now written
realistically, and a second test covers the empty-registry variant.

`tests/test_cli.py::TestSpawnStampsLineage::test_spawn_under_a_held_claim_records_its_lineage` needed
a stubbed occupancy: its caller *is* the claim-holder and was exempt only because `FLEET_WORKER`
happened to be absent from the pytest environment. That is precisely the accidental exemption this
build removes.

### 9.3 DEVIATION (minor): two comment blocks and one docstring were rewritten

- `_worker_env`'s docstring justified the stamp by a SessionStart hook deleted on 2026-07-22
  (pre-existing rot on `main`). It now states the real reason the write survives.
- `_SUPERVISOR_SHAPED_WORKER_RE`'s comment block described the arm as reading `FLEET_WORKER`. Updated,
  with an explicit note that the council's E(2) grounding is untouched by the re-key.
- Both were rewritten rather than left, because a comment asserting the old key would be the exact
  drift this file's own doctrine warns about.

### 9.4 THE BRIEF IS WRONG about the SPEC.md:334 mis-citation

Brief §7.3 says:

> `docs/SPEC.md:334` cites this prohibition as *"§6.1"*, but §6.1 is *"D1 — the boot verdict order"*;
> the env-channel section is **§6.5**. A mis-citation in the spec of record. Report it; do not fix it.

**There is no mis-citation.** `SPEC.md:334` reads *"…and §6.1 forbids keying a guard on it by name"*
— that is a **self-reference to `SPEC.md`'s own §6.1**, not to `claim-nonce.md`'s §6.1. Verified:

```
$ grep -n "^#\{1,3\} " docs/SPEC.md | awk -F: '$1<=196' | tail -3
132:## 5. The verdict engine (replaces PID liveness)
152:## 6. Dispatch contract (`dispatch_bg` @6167)
173:### 6.1 The second dispatch path -- supervisor successor (`cmd_sup_handoff_begin`)
```

Line 196 — the prohibition itself — falls under `### 6.1` at line 173, with no intervening heading.
So `SPEC.md:334` cites `SPEC.md` §6.1, and `SPEC.md` §6.1 is exactly where the prohibition lives.
The citation is correct. (`tests/test_destructive_guard.py:630`'s docstring already says
"FLEET_WORKER must never be the key (SPEC §6.1)", using the same convention.)

I changed nothing in `docs/SPEC.md`, as instructed — but the item should be struck from the
supervisor's doc-sync queue rather than acted on. Note also that `claim-nonce.md` §6.5 D5 does not
"forbid keying a guard on `FLEET_WORKER`" at all; it *depends on* such a guard. Had the brief's
reading been acted on, the citation would have been "fixed" to point at a section saying the
opposite of what the sentence claims.

### 9.5 Two smaller things worth your eye

- **A second registry read on the dispatch hot path.** `_ceiling_refuses_dispatch` now calls
  `load_registry()` twice (once inside `_caller_holds_supervisor_claim`, once inside
  `_acting_worker_name`). I left it rather than threading a shared registry through, because
  `_caller_holds_supervisor_claim` owns its own corrupt-registry degradation and rerouting that
  ownership is a larger change than this build warrants. Cost: one extra file read per
  `spawn`/`send`. On a corrupt registry the first read quarantines and the second finds no file, so
  there is no double-quarantine — but the net effect is that a corrupt registry now **exempts** the
  ceiling where it previously refused. That is moot in practice (the dispatch fails at
  `load_registry` inside the lock moments later regardless), but it is a real difference and I would
  rather you heard it from me.
- **`_require_claim_holder` now reads the registry**, which it did not before. It runs under
  `fleet_lock` on a mutating path, so quarantining a corrupt registry there is consistent with every
  other verb — but it is a new read on the supervisor's hottest path.

---

## 10. Verification tallies

| Run | Interpreter | Result |
|---|---|---|
| baseline, `main` @ `8dee4b8` | 3.13 | `2152 passed, 11 skipped` |
| baseline, `main` @ `8dee4b8` | 3.10 (floor) | `2152 passed, 11 skipped` |
| branch, final | 3.13 | `2215 passed, 11 skipped` |
| branch, final | 3.10 (floor) | `2215 passed, 11 skipped` |

TDD evidence: `tests/test_identity_registry.py` was written before any change to `bin/fleet.py` and
ran **44 failed, 13 passed** (RED). After the re-key: **57 passed** (GREEN).

Receipts: `py tools/verify_receipts.py --self-test --strict docs/specs/claim-nonce.md` →
`SELF-TEST PASSED`, `EXTRACTION SELF-TEST PASSED`, `61/62 reproduce exactly`,
`VERDICT: pass -- 0 failure(s), 1 warning(s)`. The single WARN is a `~/.claude/projects` mtime in a
pre-existing receipt pinned at `091d5fa`; the same verifier on the pre-amendment document reports the
identical single WARN (`58/59`, `pass -- 0 failure(s), 1 warning(s)`), so it is inherited, not
introduced. My three new receipts are pinned at `8dee4b8` and `2878c68`, both real commits.

Incidentally fixed: before this amendment the extraction self-test reported
`INCONCLUSIVE: the document already carries an evasion`. It now reports `PASSED` — the pre-existing
evasion was my own first draft's unclassifiable `# volatile` block, which I replaced with an
indented non-receipt (§16.2 explains in-line why the live measurement is deliberately not fenced as
a receipt: its evidence is a running process, not any commit's tree).

Fences honoured: no `git push` of any ref; no merge, rebase or cherry-pick; `main` untouched; no
`fleet` mutating verb and no `sup-*` verb; the live daemon (pid 28812) and
`~/.claude/daemon.lock` untouched; `docs/SPEC.md` unedited; nothing marked ratified; scratch files
confined to `$CLAUDE_JOB_DIR/tmp`; no other worktree touched.
