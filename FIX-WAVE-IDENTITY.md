# FIX-WAVE-IDENTITY — `fix/identity-registry-judges`

Builder: worker `id-build`. Wave: the supervisor's ruling on the break lens
(`REVIEW-BREAK-IDENTITY.md`) and the spec lens (`REVIEW-SPEC-IDENTITY.md`).
Brief: `state/tasks/briefs/id-fix-wave.md`.

**Verdict on the brief: it was right on every blocking point, including the two it
flagged itself as most exposed on.** I looked for the pushback it invited and did not
find one worth making. What I did find is one defect of the same class as Task 1, on
the path Task 2 makes load-bearing, in neither review and not in the brief — found by
the Task 8 detector the brief called droppable. Details in §9.

---

## 1. The numbers

| | py3.13 | py3.10 (floor) |
|---|---|---|
| Branch before the wave (`3649baf`, pre-rebase) | 2215 / 11 | 2215 / 11 |
| `main` at the `gate-arm` merge | 2221 / 11 | 2221 / 11 |
| **STEP 0 baseline** — rebased, artefact fixed (`0a03756`) | **2284 / 11** | **2284 / 11** |
| **Final** (`HEAD`) | **2309 / 11** | **2309 / 11** |

Delta attributable to this wave: **+25 tests, 0 regressions**. The Step 0 baseline is
reported separately exactly so that split is checkable.

Receipts: `py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/claim-nonce.md`
→ both self-tests PASSED, **60/61 reproduce exactly, VERDICT pass, 1 warning**. The
warning is the inherited `:1357` volatile one (a `091d5fa`-pinned mtime under
`~/.claude/projects`), as the brief predicted. Nothing else.

`git status --porcelain` is EMPTY at submission.

## 2. STEP 0 — the rebase, and the one red it produced

`git rebase main` (main = `7dbaef3`) applied **clean, with zero conflicts**. The brief
expected `docs/specs/claim-nonce.md` to conflict; it did not, and the reason is
structural rather than lucky: this branch's §16 is a pure append at EOF while
`gate-arm`'s §7 text is interior, so the two edits do not overlap. Both amendments are
present — `git diff main..HEAD -- docs/specs/claim-nonce.md` was a single 137-line
insertion hunk before I rewrote §16.

**The rebase did produce a red, and it is a rebase artefact, recorded as one.**
`tests/test_retired_sid_citations.py` went red in both directions. `gate-arm` cites the
four `retired_sids` writers by line number in two places in `bin/fleet.py`, and this
branch's insertions moved all four (`:4588/:5035/:8963/:12433` → `:4768/:5215/:9222/:12745`).
That harness exists so those numbers cannot rot silently, and re-pinning after a moving
edit is the deliberate one-line change its own docstring describes.

Committed **separately**, as `0a03756`, before a single fix was written — so no red that
arrived with the rebase is attributable to the fixes, and vice versa (`G-R`'s lesson).
The four numbers moved twice more during the wave and were re-pinned each time.

Rebased-tree measurement before the artefact fix: **2 failed / 2282 passed / 11 skipped**.

## 3. TASK 1 — the identity read stops quarantining the registry

`_acting_worker_identity` now reads through **`_registry_records_or_none`**.

Why that one and not `_read_registry_readonly`: its records-or-`None` shape composes
directly with the existing `registry=` parameter — `None` falls straight into the
already-present `not isinstance(workers, dict)` abstention — whereas the
`(ok, reason, data)` tuple would need unpacking here *and* at
`_caller_holds_supervisor_claim`, i.e. two spellings of one rule. The reasoning is in
the docstring at the call site, as the brief asked.

I did **not** also make the role lazy. The brief is right that laziness is not the fix
(it removes the read only on the happy path, and the role is consulted precisely when
the nonce has already failed), and having removed the quarantine there is nothing left
for laziness to buy but a micro-optimisation on a path that takes a file lock anyway.
Adding it would have been change without evidence.

**Pinned by** `tests/test_identity_fixwave.py` — behavioural, not source-level: the
seven verbs are driven against a `tmp_path` FLEET_HOME with a corrupt
`state/fleet.json`, and the file is asserted present, byte-identical, and free of
`fleet.json.corrupt*` siblings afterwards. A future refactor that reintroduces the
quarantine under a different spelling goes red.

## 4. TASK 2 — Site A, ND4(b)/(c) restored

`_ceiling_refuses_dispatch` reverts to `FLEET_WORKER`-absence as its structural arm,
ahead of any sid work, and an unresolvable identity refuses again.

**I checked the brief's reading against the ratified text before building, because this
task asked me to restore an environment read my own build removed on principle.** It
holds literally: `three-tier-command.md`:1489-1492 says *"Exempt the interface
structurally, with no sid at all … its **absence** exempts the interface unconditionally
— independent of any sid resolution"*, and `SPEC.md`:196 scopes its prohibition to *"a
future guard enforcing **a worker turn must never hold the supervisor claim**"*. The
ceiling is not that guard. My §9.5 was wrong to treat :196 as licensing the removal.

**And there is a positive reason ND4(c) is sound that my build missed, which I think is
the most transferable result of this wave.** The daemon leak *donates* a `FLEET_WORKER`
stamp; donation can only ever **add** one, and nothing anywhere removes one. So the two
directions are not symmetric:

- `FLEET_WORKER` **present** → unsound. "I am that worker" may be a lie about a long-dead
  dispatch. **This is what the claim guard read**, and it is the defect :196 names.
- `FLEET_WORKER` **absent** → sound. No fleet dispatch is anywhere in my donation chain.
  **This is what ND4(c) reads.**

My build treated the stamp as uniformly untrustworthy and deleted both directions. That
is why one removal was a fix and the other was a regression.

`_ceiling_refuses_dispatch` now, in order: (c) absent stamp → exempt, before any sid is
resolved or any registry file is opened; no sid → exempt; provably-not-the-holder →
exempt; otherwise (holder, unplaceable sid, corrupt registry, unreadable holder sid) the
ceiling applies.

**Task 2(c) dissolved inside (a)'s remedy, confirmed rather than assumed.** rb's separate
reachability correction is fixed and pinned: an interface session **can** run
`fleet sup-boot` and hold the claim carrying its own sid, so the test comment asserting
that shape is *"not a shape the fleet can produce"* recorded a false impossibility. It is
gone, and `test_the_interface_CAN_be_the_claim_holder_and_is_still_exempt` pins the
shape. The refusal string no longer says *"the interface tier is never subject to it"* —
that path **is** reachable by an interface carrying a donated stamp, so the sentence now
names the donation and points at `fleet doctor` instead.

**Two accepted costs, recorded so they are known rather than discovered.** A claim-holder
that unsets `FLEET_WORKER` escapes the ceiling — a self-inflicted escape by the one body
the ceiling exists to slow, against a control that is a speed-bump by construction, and
buying protection against it costs the human control channel, which ND1 forbids. And a
donated stamp costs an interface session the structural exemption, which fails toward
**measuring** the body rather than excusing it. Both are in the docstring and both are
pinned by name.

**The pin that encoded the wrong rule was re-scoped FIRST, deliberately**, as instructed.
`test_FLEET_WORKER_is_no_longer_a_predicate_anywhere` asserted the stamp appears exactly
once in `bin/fleet.py`, which ND4(c) contradicts at Site A. It is now
`test_FLEET_WORKER_is_not_a_predicate_at_the_CLAIM_GUARD`: it maps each read to its
enclosing function via the source, asserts the set is exactly
`{_ceiling_refuses_dispatch, _doctor_check_identity_witness}`, asserts
`_require_claim_holder` is not among them, and carries a seed check so a reworded read
cannot make it pass vacuously. Its docstring cites ND4(c) for why Site A keeps the key.

## 5. TASK 3 — the gate is restored, and the wedge survives it

`_require_claim_holder`'s worker-turn arm is a **gate** again, registry-keyed, ahead of
`read_incarnation()`. The classifier arm is deleted rather than left as a second,
unreachable opinion.

**The §16.2 wedge stays cured. This was the brief's stop-and-report condition and I
tested for it specifically rather than reasoning about it.**
`test_the_wedged_supervisor_can_still_RELEASE` and
`..._can_still_HEARTBEAT_and_CHECKPOINT` pass unmodified with the gate in place. The
mechanism is the re-key, exactly as rs said: the wedged supervisor's own registry record
is supervisor-shaped, `_is_supervisor_shaped` exempts it, and the donated worker-shaped
`FLEET_WORKER` that used to decide the refusal now decides nothing at this site. **My §16
credited that cure to the demotion. It was the re-key's, and the demotion was never
load-bearing for it.**

**The successor is verified, not trusted** (the brief asked for exactly this).
`test_the_successor_is_not_locked_out_by_the_restored_gate` pins both windows and they
survive by *independent* mechanisms — between begin and complete the successor's sid is
in no record (UNRESOLVED → abstain), and after complete it resolves to a
supervisor-shaped name (exempt by shape). Either alone would carry it.

**rb MAJOR 5 closes with the ordering — WHEN THE REGISTRY RESOLVES**, and it is pinned as
its own behaviour rather than as a side effect:
`test_the_gate_is_AHEAD_of_the_claim_read` plants a five-key legacy INCARNATION and asserts
a worker turn is refused *and* that no generation was minted for it. With the classifier
sitting after the four nonce arms, that worker walked through rule 4 on sid equality alone
and minted itself generation 1 with no `--nonce` ever passed.

> **CORRECTED IN WAVE 2 — this paragraph originally claimed the closure without
> qualification, and that was the sentence the confirmation review's MAJOR 2 attacked.** A
> registry-keyed gate is not there at all when the registry does not resolve: a corrupt
> registry, an AMBIGUOUS double match and a typed `--sid` naming an unregistered sid all
> made `_acting_worker_name` return `None`, and the same worker turn `main` refuses walked
> through here. Rule 4 then honoured bare sid equality and minted generation 1. **The
> ordering closes rb MAJOR 5 through the front door; the abstention door stayed open until
> wave 2's Task 1 closed it** by requiring the §9 legacy upgrade to have an affirmative
> *"the registry read and you are not a worker"* rather than an abstention. See §wave-2
> below for what that does and does not reach.

**One thing the restoration costs, disclosed because my §9.1's silence about the mirror
of it is what earned rb MAJOR 5.** With the gate ahead of the claim read, a worker-turn
refusal journals **nothing** — `_append_nonce_rejection` needs the claim this call never
reaches. On the branch it filed a `worker-turn` record. This is `main`'s behaviour
restored, and it satisfies the *"do not cry second-body wolf"* requirement the harder
way: by never filing the wrong kind rather than by filing a second kind. The evidence
loss is real and it is bounded — a refused worker turn leaves no trace in the rejections
log, exactly as it did before this branch existed. Re-instating the record would mean
moving the gate after the claim read, which is the ordering rb MAJOR 5 is about. I am not
willing to trade one for the other silently, so I kept `main`'s ordering and am naming
the cost here.

> **EXTENDED IN WAVE 2 — the bound above is true and it is not the whole sentence.** The
> confirmation review drove the case this record does not name: **a second body whose sid
> the registry resolves to a WORKER record presents a wrong generation, is refused at the
> gate, files nothing, and `_doctor_check_supervisor_claim` stays GREEN.** That is a
> genuine continuity failure made invisible — the class `SPEC.md`:273 exists for. It
> follows directly from the ordering disclosed above, so it is within the cost named here
> rather than a separate defect, but *"a refused worker turn leaves no trace"* and *"a
> second body that looks like a worker leaves no trace"* read very differently to an
> operator, and the second one is the true statement.
>
> The bound does hold for the case that matters, and the review drove that too: a second
> body the registry does **not** call a worker presents a wrong generation, files
> `refused`, and the doctor row goes `ok=False`. The wave did not fix the mis-filing by
> removing the filing.

## 6. TASK 4 — one function, one caller identity

`caller = sid_override or current_caller_session()` is hoisted above the gate and the
role is resolved from it. Ratified §4.3 is titled *"the sole source of caller identity"*
and says *"in both branches"*; `sid_override` is in scope.

**The consequence is pinned, not just the wording.**
`test_a_sid_override_continuity_refusal_IS_filed_as_refused` sets the ambient environment
to a worker while the caller types `--sid` for a different, non-worker sid, and asserts
the rejection kind is exactly `["refused"]` and that `_doctor_check_supervisor_claim`
returns `ok=False`. Before, that incident was classified off the *ambient* sid, filed as
`worker-turn`, and the doctor stayed green through exactly what SPEC.md:273 makes it fail
on. rb graded this wording; rs drove the consequence; rs was right.

Since the gate now precedes every nonce arm, `refused` is the only kind a continuity
failure can be filed under at all — the split that made the mis-filing possible no longer
exists.

## 7. TASK 5 — the pins, each RED before its fix

The full RED run, captured on the unfixed tree before a line of `bin/fleet.py` was
touched: **15 failed / 57 passed**.

| Pin | RED before | Green after |
|---|---|---|
| `sup-*` × 7 leave a corrupt registry untouched (parametrised by verb) | 6 of 7 verbs failed¹ | ✔ |
| `sup-heartbeat` also still SUCCEEDS on a corrupt registry | FAILED | ✔ |
| ND4(b): unplaceable sid REFUSES at 200k | FAILED | ✔ |
| ND4(b): corrupt registry REFUSES at 200k | FAILED | ✔ |
| ND4(b): AMBIGUOUS identity REFUSES at 200k | FAILED | ✔ |
| the ceiling read does not quarantine | FAILED | ✔ |
| ND4(c): absent stamp exempts, corrupt registry | FAILED | ✔ |
| ND4(c): absent stamp exempts a resolved over-ceiling holder | FAILED | ✔ |
| the refusal does not claim the interface can never see it | FAILED | ✔ |
| the re-scoped `FLEET_WORKER` predicate pin | FAILED | ✔ |

¹ `sup-handoff-begin` refused before reaching the identity read on that construction, so
it did not go red; it is covered by its own dedicated test
(`test_the_ceiling_exempt_lever_does_not_shred_the_roster`) and by the class-coverage
seed check. Recorded rather than papered over — a pin that was never red proves nothing,
and I am not claiming a red I did not observe.

Also added, answering the §8 trap directly: `test_a_HEALTHY_registry_is_not_rewritten_by
_the_identity_read_either` byte-compares the registry across a happy-path
`sup-heartbeat`. Mutation M-X's survival proved the suite said nothing about what the new
read *does to the file*, on either path.

Both new files carry seed checks. `test_the_seven_call_sites_are_all_covered` re-derives
the `verb="sup-…"` labels out of the source and asserts the parametrisation covers all of
them, so an eighth call site cannot silently narrow the claim.

## 8. TASKS 6 and 7 — the unratified invariant, and §16

**Task 6.** The invariant is marked `[PROPOSED — NOT RATIFIED DOCTRINE. See
docs/specs/claim-nonce.md §16.4 item 3.]` at the identity block, with its provenance
stated (a supervisor's task brief; present in the ratified corpus nowhere). The other two
prescriptive citations are gone rather than re-labelled: `_worker_turn_note`'s *"the
invariant above forbids…"* and `_require_claim_holder`'s were both attached to the
demotion, which no longer ships, so re-labelling them would have left prescriptive text
justifying absent code. The block also now records the tension rs raised as S-8 — read
strictly the invariant condemns the 200k ceiling refusal too, and one standard cannot be
right at one site and wrong at the other — as filed, not resolved.

**Task 7.** §16 rewritten inside §16 only. All four defects addressed:

- **(d)** §16.5 is new and is the longest subsection: Site A, `three-tier` §11.3 ND4(b)/(c)
  cited by name, all three instances, the asymmetry argument, and the post-fix ordering.
  §16.6 is also new and covers the `load_registry` class.
- **(b)** §16.3 now attributes the wedge cure to the **re-key**, states in one paragraph
  exactly what the demotion would have bought, and why that is worth something only under
  the open donated-sid hypothesis.
- **(c)** §16.4 item 1 no longer asks the operator to pick between `SPEC.md` §6.1 and
  §6.5 D5. §16.1 now shows why there is no loser: :196 constrains the guard's **key**,
  D5 requires the guard to **exist**, and a registry-keyed gate satisfies both sentences
  simultaneously. The item now asks the one question that is actually open — whether the
  demotion should be adopted.
- **(a)** §16.0 is new: a pointer block for a reader arriving from §6.5 D5 or §13 item 1,
  saying what each now describes inaccurately, placed in §16 because those sections are
  ratified and not mine.

§16 stays labelled DESCRIPTIVE and unratified. Nothing was ratified, no ratification was
drafted, and `docs/OPERATOR-GATES.md` is untouched. The stale receipt in old §16.3
(`grep -c` → `1`) is replaced with a fresh one pinned at `bf32d5e` showing both permitted
reads.

## 9. What this brief did not anticipate

**`_caller_holds_supervisor_claim` had Task 1's defect, on Task 2's path.** It read
`load_registry()` inside `except RegistryCorruptError` while documenting itself *"Read-only,
never raises: it runs on the dispatch hot path"*. So a `fleet spawn`/`send` ceiling check
against a corrupt registry **renamed `state/fleet.json` aside before deciding anything** —
and after Task 2 restores ND4(b), the refusal that follows arrives having already
destroyed the evidence the operator needs to understand it. This site is in neither
review and not in the brief. Fixed the same way, with the finding recorded in its
docstring.

**It was found by Task 8 — the task the brief marked lowest priority and droppable.** The
detector was written before it was run; its first run named this site. That is the sixth
finding of the *"`load_registry` is not a read"* class and the first one a harness found
rather than a person. It also, on the same run, flagged its own author: my first version
was a regex, and it matched the **prose** in the docstring I had just written describing
the call the function no longer makes. A detector that cannot tell a call from a sentence
about a call trains its reader to ignore it, so it is now an AST walk.

**Task 8's proposed assertion is not decidable, and I did not approximate it.** The brief
asked for *"each call site is an allowlisted mutating-under-lock site"*. "Mutating under
lock" cannot be decided from this source: `fleet_lock()` is taken by callers several
frames up (`cmd_kill` → `_cmd_kill_native`) and sometimes conditionally, so deciding it
textually needs an interprocedural analysis that would be wrong in the unsafe direction
whenever it guessed. Worse, the predicate is not even the right one — `cmd_status`,
`cmd_peek`, `cmd_result` and `cmd_wait` are CLI verbs the operator invoked directly and
are *correct* to quarantine, so "non-mutating ⇒ forbidden" is false. What I shipped is the
part that is decidable and carries the whole load: **the allowlist itself, by function
name**, with both directions asserted (no unallowlisted caller; no dead entries) and the
three moved sites named individually so a revert is loud rather than merely
unallowlisted. Adding a caller is then a deliberate edit with a reviewer looking at it,
which is the property five findings wanted. This is reported rather than approximated, as
the brief instructed.

**Two smaller ones.** `DAEMON_ENV_LEAK_REMEDY` told the operator *"Nothing in fleet keys a
decision on this variable"* — true on the branch, false the moment ND4(c) came back, and
it is the text `fleet doctor` prints. Corrected, and it now explains that the one decision
keyed on it keys on the stamp's **absence**, which donation cannot manufacture. And
`_worker_turn_note` ended with *"It only classifies a refusal the nonce already made; it
never makes one"*, which the restored gate falsifies in the message the refused caller
reads.

## 10. Non-blocking items

- **rb MINOR 7** — taken further than the minimum. `_acting_worker_identity`'s *"never
  raises"* was false (`sorted()` over non-string worker keys). Rather than weaken the
  docstring I filtered non-string keys, so the totality claim is now **true**; a
  non-string key is not a worker name under `NAME_RE` in any case. The docstring records
  both the reachability finding (JSON keys are strings, so it was a contract gap and not
  a live traceback) and the choice.
- **rs S-9** — one paragraph in `_ceiling_refuses_dispatch`'s docstring, no code change.
  Worth noting the scope shrank: with ND4(c) restored, the *structural exemption* no
  longer depends on the sid union at all. The union dependence survives only in the arms
  past (c), via `_caller_holds_supervisor_claim`, where it is ND4(a)'s intended bridge —
  and the note says so rather than restating a concern the fix already narrowed.

## 11. What I refused

Nothing. I looked hard at Tasks 2 and 3 because the brief said it was most exposed there
and because both reverse decisions I argued for at length, and in both cases the ratified
text says what the brief says it says — I quoted `three-tier`:1489-1492 and `SPEC.md`:196
against my own §9.5 and §16 before building. The one place I declined to follow the letter
of an instruction is Task 8's "mutating-under-lock" allowlist predicate, which the brief
itself pre-authorised reporting instead of approximating (§9 above).

The four items filed for the operator and excluded from this wave — the demotion
question, rs S-8, S-10's `SPEC.md`:196 doc-sync, S-2's grounding in §6.1 D1 — are
untouched. `SPEC.md`:334's "§6.1" self-reference stays struck.

---

# WAVE 2 — the gate stops being contingent on the registry

Wave 1's record above stands as written; the two paragraphs marked **CORRECTED IN WAVE 2**
and **EXTENDED IN WAVE 2** are edits to specific sentences that were wrong or incomplete,
not a rewrite of what wave 1 did.

Brief: `state/tasks/briefs/id-fix-wave-2.md`, the supervisor's ruling on the confirmation
review `C:/proga/fleet-id-c/CONFIRM-BREAK-IDENTITY.md` (verdict **MERGE-WITH-FIXES**).
Wave 1 shipped at `2c9ad6a`; wave 2 builds on it.

## W2.1 The numbers

| | py3.13 | py3.10 |
|---|---|---|
| baseline at `2c9ad6a` | 2309 passed / 11 skipped | 2309 passed / 11 skipped |
| after wave 2 | **2360 passed / 11 skipped** | **2360 passed / 11 skipped** |

**+51 tests, 0 regressions**, attributable:

| where | tests | task |
|---|---|---|
| `tests/test_identity_fixwave2.py` | +38 | Tasks 1, 2, 4 |
| `tests/test_load_registry_callers.py` | +9 | Task 3 (8) + the attribution rule (1) |
| `tests/test_identity_registry.py` | +4 net | Task 5 item 4 (5 new, 1 replaced) |

Receipts, unchanged from wave 1 and re-run on this tree:

    $ py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/claim-nonce.md
    SELF-TEST PASSED: a one-word paraphrase inside a pasted receipt is caught.
    EXTRACTION SELF-TEST PASSED: a receipt that stops being parsed is reported, not silently dropped.
    WARN  line 1357 [pinned @ 091d5fa]: ...            (the inherited volatile-mtime warning)
    parsed receipts: 60/61 reproduce exactly (57 fenced blocks, 0 unclassified, 0 volatile-skipped)
    VERDICT:         pass -- 0 failure(s), 1 warning(s)

**The RED run, captured on the unfixed tree before a line of `bin/fleet.py` was touched:
32 failed / 87 passed.** Every pin in the sections below was in it.

## W2.2 TASK 1 — the abstention door, and why it is closed at the legacy arm rather than at the gate

`_acting_worker_identity` now returns two more facts: `registry_read` and `candidates`.
`_acting_body_is_worker_turn(ident)` is the tri-state built on them, shaped exactly like
`_caller_holds_supervisor_claim` — `True` worker, `False` provably not, `None` cannot say:

| state | verdict | why |
|---|---|---|
| RESOLVED, worker-shaped | True | the ordinary refusal |
| RESOLVED, supervisor-shaped | False | `_is_supervisor_shaped`, unchanged |
| UNRESOLVED, registry READ | **False** | affirmative: the file was read and no record carries this sid |
| AMBIGUOUS, every candidate worker-shaped | **True** | the brief's first bullet: every answer is a worker turn |
| AMBIGUOUS, every candidate supervisor-shaped | False | the symmetric argument, made explicitly |
| AMBIGUOUS, mixed shapes | None | the two answers genuinely disagree |
| registry unreadable | None | the bit that was being thrown away |

**An UNINITIALISED registry counts as READ, and that distinction is load-bearing.**
`_registry_records_or_none` returns `None` for *both* "no file yet" and "unreadable", so
`_acting_worker_identity` now reads `_read_registry_readonly()`'s `(ok, reason, data)`
directly and treats `not_initialized` as a definite *"there are no records"*. Collapsing
them would have refused the §9 legacy upgrade on every fresh install — which is how I found
it, from the pin rather than from the argument.

**Two consumers, two thresholds, and that is the design rather than an inconsistency.**

- **The §6.5 gate refuses on `True` alone.** `None` still passes. The gate sits ahead of
  the claim read — which is what closes rb MAJOR 5's front door — so it cannot consult the
  nonce, and with no registry there is nothing at that point in the function that could
  tell a holder from a worker. Failing closed there would brick every supervisor verb on a
  broken `state/fleet.json`, including the `sup-release` that ends the incident.
- **The §9 legacy upgrade requires an affirmative `False`.** That arm demands no generation
  at all — bare sid equality mints generation 1 — so an abstention must not earn it. This
  is rb MAJOR 5's remaining door and it is the one that shuts.

**What the residual actually is, stated so it can be judged rather than assumed.** On an
unreadable registry a body still faces every nonce arm: rules 1–3 need a generation it was
given, and rule 5 refuses. So the only thing the abstention now buys is that a body the
registry *would* have called a worker is not told so. The compound the confirmation review
drove — minting generation 1 with no `--nonce` — needed the legacy arm, and that arm no
longer takes it.

**I did not push back, and I checked whether I should.** The brief invited a stop-and-report
if the abstention lane could not be made safe as described, or if closing it cost a body the
review confirmed passes. Neither happened: the shape the brief ordered is implementable as
written, the roster is green throughout (`TestTheFailClosedRoster`, seven members, each
pinned individually), and the lane the brief said to leave open is left open *and pinned
open* (`test_a_CORRUPT_registry_still_passes_the_gate_and_that_is_DISCLOSED`) so that moving
it later is a deliberate edit rather than a silent one.

**One thing the new refusal deliberately does NOT do: file a rejection.** The legacy-arm
refusal raises without `_append_nonce_rejection`. The state it fires on is a legacy claim, a
caller whose sid *equals* the holder's, and a registry that cannot be read — overwhelmingly
the real holder plus a broken file. `refused` is the row `SPEC.md`:273 makes the doctor fail
on **as evidence of a second body**, and filing it here would cry wolf on the holder's own
turn. Pinned as a choice (`test_the_refusal_does_not_cry_second_body`), not left implicit.
It does mean this wave adds one more member to the "refusals that leave no trace" list,
alongside the inherited §9 sid-mismatch refusal the brief excluded from this wave.

## W2.3 TASK 2 — the seventh instance

`_supervisor_gate`'s send carve-out reads `_registry_records_or_none()` instead of
`load_registry()` inside `except RegistryCorruptError`, and the `_supervisor_gate` entry is
deleted from the detector's `ALLOWED` with the reasoning left in place of it. The fail
direction is unchanged: no readable registry means no proof that the target IS the holder,
so the carve-out declines and the gate stays armed.

`test_a_corrupt_registry_SURVIVES_a_refused_send` drives the real verb end to end and then
looks at the filesystem — the file is still there, still byte-identical, and no quarantine
copy appeared beside it. The two carve-out behaviours (holder target ungated, non-holder
target gated) are pinned alongside it so the swap cannot quietly widen or narrow seam #1.

**Attribution, restated because the brief measured it before ordering the fix:** the call is
byte-identical on `main` and this branch did not mint it. What this branch minted is the
allowlist entry that certified it, filed under *"all inside `fleet_lock()`"* — which is
false — and against the list's own admission rule, both of whose disqualifiers applied.

## W2.4 TASK 3 — the detector's three static evasions

`_callers()` walks class bodies and nested classes (`Class.method`, `Outer.Inner.method`,
`Class.<class body>`), module level (`<module>`, a name no allowlist entry can accidentally
already carry), and resolves module-level aliases as a **fixpoint** so a chain buys nothing
a single hop does not. Attribution *within* a function is still to the outermost enclosing
function, and that rule is now pinned rather than assumed.

`getattr` dispatch is **not** closed and cannot be. The docstring says so, the file's scope
paragraph says so, and `test_getattr_dispatch_is_UNDECIDABLE_and_the_docstring_says_so`
pins the honesty rather than the capability — including that the sentence survives a
reflow, because a docstring's honesty must not be hostage to where the line wrapped.

`test_the_evasions_are_offenders_against_the_REAL_allowlist` is the half that matters: the
walk finding them is not enough, the assertion has to reject them.

## W2.5 TASK 4 — `sup-boot`

One call site, as the brief predicted, using the same predicate at the same threshold —
because a body `sup-boot` admits and every other verb refuses IS the wedge, and that
agreement is itself pinned (`test_the_boot_gate_and_the_verb_gate_agree`). It sits ahead of
the roster subprocess: a refused boot should not pay for a `claude agents --json` it will
not use, and `test_the_refused_boot_writes_NOTHING` asserts no INCARNATION and no journal
entry, because a refusal that still wrote a claim would be the same wedge with an error
message on top. A gen-0 `sup|<launch-id>|boot` body, an UNRESOLVED interface session, the
successor in `--handoff-inc` mode and a corrupt registry all still boot.

## W2.6 TASK 5 — the disclosures

1. **§5 corrected.** rb MAJOR 5 closes with the ordering *when the registry resolves*; the
   abstention door is named, and Task 1 is named as what closes it.
2. **§16.3 now states where the gate is ABSENT rather than lenient**, in its own paragraph
   ahead of the argument, and §16.4 item 1 says what that means for the demotion ruling the
   operator is being asked to make: a ruling to keep the gate is a ruling about a control
   with that hole in it, and a ruling to demote gives up a control present in every
   readable state.
3. **Target 5's un-named extension added** to the disclosed cost in §5: a second body whose
   sid the registry resolves to a *worker* record is refused at the gate, files nothing, and
   `_doctor_check_supervisor_claim` stays **GREEN**. It follows from the ordering wave 1
   disclosed, so it is within the cost already named — but *"a refused worker turn leaves no
   trace"* and *"a second body that looks like a worker leaves no trace"* read very
   differently, and the second is the true one.
4. **The escape is now detected.** `_doctor_check_identity_witness` **fails** on
   registry-RESOLVED + witness-gone — the one on-box state that falsifies *"absent ⇒ no
   fleet dispatch is in my donation chain"*, and precisely what a blanked stamp produces.
   Blanks (`""`, `"   "`, `"\t"`, `"\n"`) are pinned as reddening too, since they are what
   the `.strip()` makes indistinguishable from unset. `DAEMON_ENV_LEAK_REMEDY` was true of
   donation and silent about removal; it now says both, and §16.5 records it. ND1 forbids
   *preventing* the escape and says nothing about *detecting* it.

## W2.7 What I refused, and what moved that was not asked for

**Refused: nothing in the brief.** The one place I went beyond the letter of an instruction
is Task 1's *"AMBIGUOUS, all candidates non-supervisor-shaped → REFUSE"*: I also made
**AMBIGUOUS, all candidates supervisor-shaped → `False`**, explicitly, rather than letting
it fall into `None`. The brief's own reasoning demands the symmetric case — if "every answer
is a worker turn" refuses, then "no answer is a worker turn" must not merely abstain — and
leaving it as an abstention would have made the shipped rule read *"ambiguity refuses"*,
which is not what was ordered. It is pinned in its own test.

**Two behaviours changed that existing tests asserted, both ordered by the brief and both
rewritten rather than deleted:**

- `test_an_ambiguous_body_passes_through_to_the_nonce` planted two ordinary workers and
  asserted they passed. It is now `..._of_MIXED_SHAPE_...` and asserts the ambiguity that is
  genuinely mute; the all-worker case moved to `test_identity_fixwave2.py` as a refusal.
- `test_no_witness_no_finding` asserted `ok=True` on registry-RESOLVED + witness-gone. That
  is the state Task 5 item 4 orders reddened; it is replaced by four tests that pin which
  witness-absent states stay green and which one does not.

**One thing I moved that the brief did not ask for, disclosed because it is a spelling
change on a hot read:** `_acting_worker_identity` reads `_read_registry_readonly()` rather
than `_registry_records_or_none()`. Both are *"never writes, never quarantines, never
raises"* and the detector treats neither differently; the reason is the `not_initialized`
paragraph in W2.2, and §16.6's sentence claiming both identity reads go through
`_registry_records_or_none` is corrected rather than left to rot.

**The four `retired_sids` writer citations were re-pinned** (`:4955, :5402, :9452, :13111`),
as they are on any wave that changes line counts in `bin/fleet.py`. Mechanical, and the
citation harness is what forces it.

**The four operator questions are untouched.** The demotion (§16.4 item 1), rs S-8's scope
clause, S-10's `SPEC.md`:196 doc-sync, and S-2's grounding in §6.1 D1 stay filed and
unanswered; Task 5 corrects what the operator will *read* about them and answers none of
them. `docs/OPERATOR-GATES.md`, `docs/SPEC.md`, `three-tier` §11.3 and claim-nonce §6.5 D5 /
§13 are unedited. MINOR 2 (`fleet doctor` quarantining the registry it was invoked to
diagnose) is left alone as the brief directs, and so is the inherited §9 legacy-arm unfiled
refusal.
