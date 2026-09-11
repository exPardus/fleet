# §7 exemption envelope — four-councilor synthesis and interface ruling

**Status: INTERFACE RULING, PROVISIONAL — taken under the operator's standing directive 7, PENDING
OPERATOR RATIFICATION.** The operator is away with standing autonomous authorization and a standing
instruction that operator-gated blocking items go to a four-councilor council whose synthesis is
acted on and recorded. This is that record. **No box in `docs/OPERATOR-GATES.md` has been ticked** —
a ratification request is filed there under `## Open`.

Convened 2026-07-28 by the interface tier against `main` @ `b7c5c85`. Four independent fleet workers,
lenses **risk / delivery / strategist / incident**, no shared context, no visibility of each other's
verdicts. Question: `docs/decisions/W9-section7-exemption.md`, raised by `inc-20260727T232026Z-06cf`.

---

## HEADLINE: the escalation's sharpest claim is FALSE, and two lenses killed it independently

The supervisor carried this forward as doctrine, and my own council brief repeated it:

> *"Repairing the handoff makes the `sup-recover` refusal MORE frequent, not less — every stillborn
> successor leaves a `handoff_token_hash` on a `held` claim and §5.7 mandates refusal there."*

**Measured, twice, by two lenses that could not see each other:**

`cmd_sup_release` (`bin/fleet.py:12918-12925`) builds the released claim as a **fresh six-key dict**
— `incarnation_id, lineage_id, claimed_via, released_at, released_by_sid, state` (+ optional
`reason`) — and `write_incarnation` (`:10334`) writes it verbatim. **`handoff_token_hash` is never
copied.** Therefore:

> **§5.7 can NEVER fire on arm 4 or arm 5 — the released arms, which are the ones the real outage
> instantiates. §5.7 and §7 do not overlap at all.**

The direction is also backwards. The hash clears only via `drop_handoff_entry` (`:10880-10912`),
reached from `sup-handoff-complete`/`-abort`. A stillbirth runs neither, so the hash persists until a
human intervenes — and pre-`fix/handoff-seams` a stillborn handoff was *literally unabortable*. A
**successful** handoff completes in ~45s. **Repairing the handoff shortens the refusal window from
unbounded-until-manual-intervention to ~45s. Repair makes it rarer and shorter, not more frequent.**

And the premise underneath it: `grep -c "sup_recover\|sup-recover" bin/fleet.py` → **0**. The verb
does not exist. The inversion was spec-reasoning about an unbuilt front door against an unrepaired
mechanism.

**It travelled through a break lens → a supervisor journal → a decision doc → my council brief,
gaining authority at each hop and evidence at none.** That is the *"0 turns"* shape exactly, and it is
the second instance this week. The retraction is the most valuable output of this council.

**Consequence:** the two questions were fused. The inversion was offered as evidence for the **§7**
half and is entirely a **§5.7** matter. *That fusion is what made a two-arm problem read as a
principle-level conflict.*

---

## POSTSCRIPT — the wave-10 supervisor corrected this synthesis within the hour. It is right.

`inc-20260727T235933Z-8455`, acting on break lens `gate-acg-rb`'s MAJOR-1 and re-verifying all three
citations itself against `main` @ `b7c5c85` rather than relaying them:

**My Verdict A presumed a settled exemption to re-ground. There was none.** §7's ratified text is
*internally ambiguous about `autoclean`, and its only disambiguator is dead*:

- `claim-nonce.md:2023` says *"`autoclean` is **structurally** exempt"* — and **"structurally" is
  itself the qualification**, not a synonym for "unconditionally."
- `claim-nonce.md:2091-2092` is the one place that said what "structurally" meant: it keyed the
  exemption on **the scheduled task's absent `CLAUDE_CODE_SESSION_ID`**. That caller is retired.
- **`claim-nonce.md:2174` — the same ratified block makes the verb taxonomy BINDING, and that
  taxonomy lists `autoclean` in the Mutating-lifecycle (GATED) row.**

So the ratified text says *exempt* in one line, *gated* in its binding table, and the sentence that
reconciled them describes a caller that no longer exists. **The council re-grounded the exemption and
never addressed `:2174`.** The supervisor's verdict, which I accept verbatim:

> **A re-grounding that does not fix `:2174` leaves the ratified text exactly as self-contradictory as
> it is today, with a better paragraph attached.**

It has ordered the `:2174` repair on the branch as part of directive 1. **That repair is a condition of
Verdict A, not an optional follow-up** — and the operator's ratification request has been amended to
say so, because it is an amendment to operator-owned text my synthesis did not itemise.

**Question A as originally asked was the wrong question.** Not *"does the exemption stay
unconditional?"* but *"how do you want §7 disambiguated?"* — of three available shapes the council
chose the third (keep the behaviour, rewrite what grounds it, fix `:2174`). Recorded so shape 2 is not
revisited by accident: conditioning the sweep on caller-sid-matches-claim-holder does not merely fail
for the interface ritual, it **re-breaks the sweep for a fleet with no supervisor** — the exact failure
the branch fixes and the exact reason the interface ritual runs `autoclean` at all.

**Two corrections to my risk framing, both measured:** tier 3 is **default-OFF** and *neither driver
passes `--expire-tombstones-hours`*, so the exempt surface does not expire tombstones in practice; and
`cmd_archive`'s mutations were never guarded by §7 alone — six independent `_archive_eligible` gates
run per record, so a divergent body running the sweep cannot archive the live supervisor, cannot
archive a live worker, and cannot `claude rm` a live sid.

**This is the correct outcome and the reason the ruling was published rather than held.** A provisional
interface ruling that survives contact with a hostile lens is worth more than one nobody tested; this
one did not survive intact, and it is better for it.

---

## VERDICT A — `autoclean`'s §7 exemption: **RE-GROUNDED**. Unanimous, 4/4.

The exemption **stays**. Its stated ground is retired and replaced. All four lenses converged
independently; the ground below is their common core.

> **`autoclean` is exempt because it is a convergent janitorial sweep with no dispatch, steer, or
> claim authority.** Every action it can take is already conditioned on the target being
> terminal-state, roster-confirmed-gone, outcome-vouched and past TTL, so a divergent body running it
> produces byte-for-byte what the legitimate body produces on its next beat. It is structurally
> incapable of the harm §7 guards, and it **must** run precisely while a claim is held, because a
> live fleet is the only condition under which husks accumulate. The exemption is a property of the
> **sweep's effect**, not of the caller's environment.

Strictly better than what it replaces: *"the scheduled task has no session id"* was a claim about
**configuration** and was falsified by a configuration change in one day. This is a claim about
**effect**, falsifiable only by deliberately widening what the sweep does.

**Two binding riders**, both carried by more than one lens:

1. **The exemption is carried explicitly at every frame and never inherited from the call graph.**
   This is *"the exemption is not transitive"* turned from a lesson into a rule. `as_autoclean_tier`
   is the correct shape **because it is a parameter** — a thing a reader can see at the frame where
   it applies, and the one thing that cannot be silently assumed one frame down.
2. **It is scoped to the sweep's current effect set.** Any new tier, or any widening past
   "terminal + roster-confirmed-gone + outcome-vouched", **re-opens this question**. The exemption
   dies at any frame that takes a lifecycle action against a live body.

### Verified, not asserted

- **Risk lens verified `fix/autoclean-archive-gate` @ `e4a0730`'s non-narrowing claim by reading the
  diff: TRUE.** Two-line signature change, an `if not as_autoclean_tier:` guard, one call site passing
  `True`. No `--as-autoclean-tier` flag; the dispatch table calls `cmd_archive(args)` positionally, so
  the CLI can only ever reach the `False` default. Armed-verb set unchanged, pinned by two tests.
- **Incident lens drove the refusal from a third independent caller** (a worker sid, neither of the
  two in the docket), `--dry-run`, no writes. **CONFIRMED — three independent drives.** This clears
  the *"evidence from the component suspected of being broken"* test the docket needed to pass.
- **Risk lens closed the one path back to a silently-disarmed gate:** `_archive_eligible` gate 3b
  refuses the record a `released` claim is currently wedging the fleet on, via `_releaser_live_sids`
  — *the same predicate `_supervisor_gate` arms on*. The exempt surface cannot delete the state the
  gate reads. Already closed, independently of §7.

### A live R2 violation the docket did not report

`autoclean --help | grep -c nonce` → **0**; `archive --help` → **2**. The refusal names `--nonce` as
the remedy, and **for both real callers that remedy is unreachable** — the interface has no
generation to present, and the supervisor beat has no flag to present one through. This is *"a named
remedy that always fails"*: the exact shape the 2026-07-26 **R2** ruling forbids, shipping on every
sweep. Route A is not a convenience defect. It is a live R2 violation.

### Correction to the urgency, against my own brief

Delivery lens measured it and I had it wrong in two ways:

- **The sweep is not "broken on every run."** `cmd_autoclean` has tier isolation: tier 1's exception is
  caught, tiers 2 and 3 run regardless. Of 38 `autoclean_run` events, **exactly 2** carry the gate
  error.
- **Husks are tier 2, which is not gated and is working.** What accumulates is *unarchived terminal
  registry records*: **4 eligible now**, with 44 in `ttl-not-elapsed` behind them. A floor, not a
  level — it decays within a day, but the emergency framing was mine and it was wrong.

---

## VERDICT B — `sup-recover` and §7: **PARTIAL. Arm 5 only. Arms 3 and 6 are NOT ruled.**

Split 3–1 on granting relief, and the split is narrower than it looks. The councilors mapped §7's
arming against every `sup-recover` arm — something the docket's prose did not do — and the map is
what decides it:

| Arms | §7 today | Ruling |
|---|---|---|
| 2, 4, 7, 9 | **already disarmed** | **No exemption needed.** Nothing to grant. These are the arms the incident record actually instantiates. |
| **5** — released, releaser roster-live | **ARMED, unconditionally, NO continuity path** | **RELIEF GRANTED, provisionally.** |
| **6** — held, holder `limited` | armed ≤3600s | **NOT RULED — deferred to the operator.** |
| **3** — held, holder alive and beating | armed | **NOT RULED — must genuinely wait. Inherits `respawn supervisor`'s gate unchanged.** |
| 8 | armed, first hour | No relief. The arm refuses by default anyway; `--force-frozen` is a typed assertion. |

**The docket's CRITICAL-1 — *"refused on exactly the states it exists to clear"* — is true of one arm
out of nine, not of the class.** Stating the gated arms without the ungated ones is what turned two
arms into a principle-level conflict.

### Why arm 5 gets relief, and why it is a discharge rather than a widening

Arm 5 is the only state in the whole gate where **the refusal names a remedy that cannot exist**.
§6.3 strips the key set on release, so `_nonce_presentation` returns `None` for every caller and
every value — there is no generation to present because there is no claim to prove continuity *on*.
`_wedged_release_gate`'s own docstring concedes exactly this and calls offering `--nonce` there *"a
named remedy that always fails, which is the exact defect the 2026-07-26 ruling (R2) forbids."*

`claim-nonce` §7.2 already records the matching debt: *"no in-fleet disarm … is owed work; the
human-at-a-shell exit is explicitly NOT ratified."* **Arm 5 IS that owed path.** Granting relief there
discharges a debt the operator acknowledged on 2026-07-27; it does not open an envelope they have not
seen. Arm 5 is not a state that *resembles* the gate's armed state — since `fix/sup-release-tombstone`
it partitions on **the identical predicate**, so exempting it is a definition, not a carve-out.

### Why arms 3 and 6 are not mine to rule

- **Arm 3 dispatches over a live, beating, claim-holding supervisor.** No operator ruling covers that.
  The evening 2026-07-27 gate named the *released* state and the *two walls* — never "the holder is
  healthy." Letting an unauthenticated interface verb replace a live claim-holder **is** the
  two-live-supervisors condition, and the same gate refused its neighbour (*"not auto-spawn"*).
- **Arm 6 is contested 2–2, and both lenses that granted it named it their own weakest half.** Risk:
  *"if `sup-boot` is ever gated, my arm-6 exemption becomes a genuine widening"* — a defense resting
  on an unratified property. Incident, against itself: *"if arm 6 is the modal outage rather than arm
  5, my narrowing re-creates the ratified debt one arm to the left."* Two lenses arguing against
  their own grant is exactly where an interface should stop.

### §5.7's handoff-token refusal: **STAYS**

3 of 4. The dissent (strategist) argued it is R2-defective and must be re-keyed onto the handshake
timeout. **The measurement above dissolves the dissent's premise**: §5.7 can never fire on the
released arms, so it does not stand over the states `sup-recover` exists to clear.

**One owed repair, separately:** §5.7 names `sup-handoff-complete`/`-abort` as escapes, and
`cmd_sup_handoff_abort` gates through `_require_claim_holder`, which the body that is gone is the only
one able to satisfy. Two lenses found this independently. It is a **third item**, closed by neither
question A nor question B, and it should be filed rather than folded in here.

---

## The principle, synthesised

> **A guard may demand only a proof that every legitimate caller can construct and the body it fears
> cannot. Where no legitimate caller can construct it, the guard yields on that state alone — and
> every such exemption is an explicit parameter at the frame where it applies, never a property of
> the call graph.**

The first clause decides arm 5 and refuses arms 3 and 6 in the same breath. The second decides A and
is the anti-transitivity rule the `cmd_autoclean` → `cmd_archive` wound bought.

---

## What I am directing on this ruling

1. **Merge `fix/autoclean-archive-gate` @ `e4a0730` at its queue position**, with §7's decision block
   re-grounded in the same merge. Delegable: it implements a sentence the operator ratified on
   2026-07-23 that shipped code contradicts, and it closes a live R2 violation.
   **Note, measured by the delivery lens: the branch is 407 insertions across 11 files and writes a
   new open gate into `docs/OPERATOR-GATES.md`. Merging and ruling are not independent acts.**
2. **Arm 5 relief may be built. Arms 3 and 6 may not**, and no builder may un-gate arm 3.
3. **Retract the inversion** wherever it is recorded — decision doc, supervisor journal, lessons.
4. **File two items this council opened and neither question closes:** (a) `sup-handoff-abort`'s
   claim-holder requirement is unsatisfiable by its own audience; (b) the token-drop-on-release is a
   **structural property with no test pinning it** — a builder obligation.
5. **Ambiguity A2 is answered and is not an operator question.** The succession spec escalated
   *"§6.3 lists `handoff_token_hash` in neither the kept nor the removed set"* as undecidable from the
   text. It is decidable from the code in one read: **dropped.** Pin it, then close it.

## Citation corrections — found by all four lenses independently

- **`_wedged_release_gate` is at `bin/fleet.py:11867`, not `:12183`** — off by 316 lines. The error is
  in `docs/decisions/W9-section7-exemption.md` and was repeated in all four of my council briefs,
  which each warned the reader not to trust line numbers and then supplied a rotted one. Corrected in
  the decision doc.
- **`docs/specs/graceful-succession.md` does not exist on `main`** — it lives only on
  `spec/succession-signal`. A reader following the docket from a clean checkout finds nothing. **Name
  the ref, not just the path.**
- **`_supervisor_boot_decision` does not exist**; the symbol is `supervisor_claim_decision`. Its
  conclusion held under verification, but the shipped comment at `bin/fleet.py:6101` relied on for the
  opposite claim is **false** — a plain `sup-boot` seizes straight through a token-carrying claim.
- **`handoff-fix` and `acgate` are not branch names**; they are `fix/stillborn-handoff` @ `87cbf9a`
  and `fix/autoclean-archive-gate` @ `e4a0730`.

## Councilor dissents, preserved

- **Delivery — NO EXEMPTION on B.** Arm 5 is reachable today via the no-sid route, so it is a UX
  defect, not a capability lockout; *"`autoclean` converges, `sup-recover` creates,"* and that
  asymmetry is why A gets an exemption and B does not. **Partially self-undercut by its own finding
  6:** `cmd_sup_spawn` is also §7-gated, so the three-command alternative is reachable by the
  interface *only via the same no-sid bypass* — the alternative is not gate-free. Its sequencing
  argument survives intact and I have adopted it: defer the build, sever the succession spec's Part 1
  (the signal, ~460 buildable lines) which addresses the measured outage and carries no gate content.
- **Strategist — §5.7 must move, re-keyed onto the handshake timeout.** Premise dissolved by the
  released-dict measurement above. Its **binding amendment is adopted**: if relief is implemented,
  **keep the record, drop the refusal** — `sup-recover` must journal a divergence observation when the
  caller presents no valid generation, then proceed. §7's value on this verb was never the refusal; it
  was the `refused` journal record, which is the divergence detector's input. A builder who implements
  the relief without that record has shipped the counter-argument instead of the verdict.
- **Risk — arm 6 should join arm 5**, on the ground that `fleet sup-boot` is ungated today so the
  exemption changes cost, not capability. Deferred here precisely because that ground is unratified,
  which risk itself flagged.
